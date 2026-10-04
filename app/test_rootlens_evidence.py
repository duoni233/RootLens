import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from core.evidence import Evidence, EvidenceBundle, QueryContext, WindowPolicy
from evaluation.rootlens_baseline import suite_fingerprint
from evaluation.rootlens_cases import load_rootlens_cases
from mcp.incident_tools import DEFAULT_RUNTIME_ROOT, LEGACY_RUNTIME_ROOT, IncidentTools
from mcp.tool_manager import MCPToolManager, Tool, ToolResult

NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)
TOOLS = ("query_logs", "query_metrics", "query_deployments")


def context(**changes):
    values = dict(service_name="payment-service", environment="demo",
                  anchor_time="2026-09-01T10:05:00+08:00", timezone="Asia/Shanghai",
                  dataset_id="rootlens-demo", dataset_version="v2")
    values.update(changes)
    return QueryContext.build(**values)


@pytest.fixture
def handlers():
    return IncidentTools(clock=lambda: NOW)


@pytest.fixture
def manager(handlers):
    manager = MCPToolManager(api_key="offline-test-key")
    manager._client.messages.create = AsyncMock(side_effect=AssertionError("no LLM calls"))
    handlers.register(manager)
    yield manager
    manager._client.messages.create.assert_not_called()
    asyncio.run(manager._client.close())


def call(manager, name, ctx=None, **changes):
    params = (ctx or context()).tool_params(name)
    params.update(changes)
    return asyncio.run(manager.call(name, params))


@pytest.mark.parametrize("name,ids", [
    ("query_logs", ["L003", "L001", "L002", "L004"]),
    ("query_metrics", ["M001", "M002", "M003"]),
    ("query_deployments", ["D002", "D001"]),
])
def test_scope_windows_boundaries_and_order(manager, name, ids):
    result = call(manager, name)
    assert result.success and result.error is None
    assert [item["record_id"] for item in result.data] == ids
    assert all(item["service_name"] == "payment-service" and item["environment"] == "demo"
               for item in result.data)
    assert all(item["evidence_category"] == "operational" for item in result.data)


@pytest.mark.parametrize("name", TOOLS)
@pytest.mark.parametrize("changes,expected", [
    ({"service_name": "order-service"}, 1),
    ({"environment": "prod"}, 1),
    ({"environment": "staging"}, 0),
    ({"service_name": "missing-service"}, 0),
    ({"anchor_time": "2026-09-03T10:05:00+08:00"}, 0),
])
def test_service_environment_and_empty(manager, name, changes, expected):
    ctx = context(**changes)
    result = call(manager, name, ctx)
    assert result.success and result.error is None
    assert len(result.data) == expected
    assert all(item["service_name"] == ctx.service_name
               and item["environment"] == ctx.environment for item in result.data)
    bundle = EvidenceBundle.from_results(ctx, {name: result})
    assert bundle.tool_status[name].status == ("ok" if expected else "empty")


def test_deployments_lookback_and_exact_anchor(manager):
    result = call(manager, "query_deployments", version="v2.3.7")
    assert [item["observed_at"] for item in result.data] == ["2026-09-01T10:00:00+08:00"]
    point = call(manager, "query_deployments", start_time="2026-09-01T10:00:00+08:00",
                 end_time="2026-09-01T10:00:00+08:00")
    assert [item["record_id"] for item in point.data] == ["D001"]


def test_filters_limit_and_metric_interval(manager):
    logs = call(manager, "query_logs", error_code="DBConnectionError", limit=1)
    assert [item["record_id"] for item in logs.data] == ["L001"]
    metrics = call(manager, "query_metrics", metric_names=["db_pool_in_use"])
    assert [item["record_id"] for item in metrics.data] == ["M003"]
    # An aggregate spanning beyond the requested end cannot be treated as fully in scope.
    partial = call(manager, "query_metrics", end_time="2026-09-01T10:05:30+08:00")
    assert [item["record_id"] for item in partial.data] == ["M001"]


@pytest.mark.parametrize("changes", [
    {"start_time": "10:05"}, {"start_time": "2026-09-01T10:05:00"},
    {"start_time": "2026-09-02T10:05:00+08:00"},
    {"limit": True}, {"limit": 0}, {"dataset_version": "v1"},
    {"service_name": " "}, {"unexpected": "expected_diagnosis"},
])
def test_invalid_queries_are_failures_not_empty(manager, changes):
    result = call(manager, "query_logs", **changes)
    assert not result.success and result.error and result.data is None
    bundle = EvidenceBundle.from_results(context(), {"query_logs": result})
    assert bundle.tool_status["query_logs"].status == "failed"


def test_context_requires_complete_time_and_configurable_windows():
    with pytest.raises(ValidationError):
        context(anchor_time="2026-09-01T10:05:00")
    ctx = context(anchor_time="2026-09-01T02:05:00Z",
                  policy=WindowPolicy(lookback_minutes=2, lookahead_minutes=3,
                                      deployment_lookback_minutes=30))
    assert ctx.anchor_time.isoformat() == "2026-09-01T10:05:00+08:00"
    assert ctx.logs_window.start_time.isoformat() == "2026-09-01T10:03:00+08:00"
    assert ctx.deployments_window.start_time.isoformat() == "2026-09-01T09:35:00+08:00"


def test_stable_ids_raw_refs_and_retrieval_time(manager, handlers):
    first = call(manager, "query_logs")
    uncached = asyncio.run(manager.call("query_logs", context().tool_params("query_logs"),
                                       use_cache=False))
    assert first.data == uncached.data
    ids = [item["evidence_id"] for item in first.data]
    assert len(ids) == len(set(ids))
    for item in first.data:
        record = handlers.resolve_raw_ref(item["raw_ref"])
        assert record.record_id == item["record_id"]
        assert record.attributes.model_dump() == item["attributes"]
        assert item["retrieved_at"] != item["observed_at"]


def test_cache_preserves_actual_retrieval_timestamp(manager, handlers):
    first = call(manager, "query_logs")
    handlers.clock = lambda: datetime(2026, 9, 3, tzinfo=timezone.utc)
    cached = call(manager, "query_logs")
    fresh = asyncio.run(manager.call("query_logs", context().tool_params("query_logs"),
                                    use_cache=False))
    assert cached.cached and cached.data == first.data
    assert not fresh.cached and fresh.data[0]["retrieved_at"] != first.data[0]["retrieved_at"]
    assert fresh.data[0]["evidence_id"] == first.data[0]["evidence_id"]


def test_evaluation_is_never_read_or_used(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    shutil.copytree(DEFAULT_RUNTIME_ROOT, runtime)
    evaluation = tmp_path / "evaluation"
    evaluation.mkdir()
    expected = evaluation / "INC-001.expected.json"
    expected.write_text('{"expected_diagnosis":"answer A"}', encoding="utf-8")
    original = Path.open
    opened = []

    def guarded_open(path, *args, **kwargs):
        opened.append(path.resolve())
        if evaluation in path.resolve().parents:
            raise AssertionError("runtime attempted to read evaluation")
        return original(path, *args, **kwargs)

    def query_all():
        loader = IncidentTools(runtime, clock=lambda: NOW)
        with monkeypatch.context() as patch:
            patch.setattr(Path, "open", guarded_open)
            return [asyncio.run(getattr(loader, name)(context().tool_params(name)))
                    for name in TOOLS]

    before = query_all()
    expected.write_text('{"expected_diagnosis":"completely different answer"}', encoding="utf-8")
    assert query_all() == before
    assert opened and all(runtime in path.parents for path in opened)
    with pytest.raises(ValueError):
        IncidentTools(evaluation)
    loader = IncidentTools(runtime, clock=lambda: NOW)
    with pytest.raises(ValueError):
        loader.resolve_raw_ref("../evaluation/INC-001.expected.json#L001")


def test_symlink_escape_is_rejected(tmp_path):
    runtime = tmp_path / "runtime"
    shutil.copytree(DEFAULT_RUNTIME_ROOT, runtime)
    source = runtime / "INC-001" / "logs.json"
    outside = tmp_path / "outside.json"
    outside.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    source.unlink()
    try:
        source.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable on this platform")
    loader = IncidentTools(runtime, clock=lambda: NOW)
    with pytest.raises(ValueError, match="escapes"):
        asyncio.run(loader.query_logs(context().tool_params("query_logs")))


def test_malformed_runtime_record_fails_closed(tmp_path):
    runtime = tmp_path / "runtime"
    shutil.copytree(DEFAULT_RUNTIME_ROOT, runtime)
    source = runtime / "INC-001" / "logs.json"
    records = json.loads(source.read_text(encoding="utf-8"))
    records[0]["expected_diagnosis"] = "must not be accepted"
    source.write_text(json.dumps(records), encoding="utf-8")
    with pytest.raises(ValidationError):
        asyncio.run(IncidentTools(runtime).query_logs(context().tool_params("query_logs")))


def test_bundle_deduplicates_and_rejects_knowledge_or_out_of_scope(manager):
    valid = call(manager, "query_logs")
    duplicate = ToolResult(success=True, tool_name="query_logs", data=valid.data * 2)
    bundle = EvidenceBundle.from_results(context(), {"query_logs": duplicate})
    assert len(bundle.evidence) == len(valid.data)
    altered = dict(valid.data[0], evidence_category="knowledge", source_type="runbook")
    with pytest.raises(ValidationError):
        Evidence.model_validate(altered)
    for change in ({"service_name": "order-service"}, {"environment": "prod"},
                   {"observed_at": "2026-09-02T10:05:00+08:00"}):
        invalid = ToolResult(success=True, tool_name="query_logs",
                             data=[dict(valid.data[0], **change)])
        bundle = EvidenceBundle.from_results(context(), {"query_logs": invalid})
        assert not bundle.evidence and bundle.tool_status["query_logs"].status == "failed"


def test_bundle_rejects_fallback_facts_and_keeps_partial_evidence(manager):
    metrics = call(manager, "query_metrics")
    degraded = ToolResult(success=True, tool_name="query_logs", error="timeout",
                          data=[{"summary": "invented fallback"}])
    bundle = EvidenceBundle.from_results(context(), {"query_logs": degraded,
                                                   "query_metrics": metrics})
    assert bundle.tool_status["query_logs"].status == "degraded"
    assert bundle.tool_status["query_deployments"].status == "failed"
    assert bundle.evidence and all(item.source_type == "metric" for item in bundle.evidence)


def test_existing_timeout_and_circuit_breaker_are_reused(manager):
    async def slow(params, ctx):
        await asyncio.sleep(1)
        return []

    manager.register(Tool(name="slow", description="test only", handler=slow,
                          schema={"type": "object"}, timeout_s=0.001))
    manager._tools["slow"].breaker.threshold = 1
    first = asyncio.run(manager.call("slow", {}))
    second = asyncio.run(manager.call("slow", {}))
    assert not first.success and not second.success
    assert "超时" in first.error and "熔断" in second.error


def test_v2_snapshot_preserves_v1_and_changes_only_m401_summary():
    old = json.loads((LEGACY_RUNTIME_ROOT / "manifest.json").read_text(encoding="utf-8"))
    new = json.loads((DEFAULT_RUNTIME_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert old["dataset_version"] == "v1"
    assert new == dict(old, dataset_version="v2")
    for incident in old["incident_ids"]:
        for filename in ("logs.json", "metrics.json", "deployments.json"):
            before = json.loads((LEGACY_RUNTIME_ROOT / incident / filename).read_text(encoding="utf-8"))
            after = json.loads((DEFAULT_RUNTIME_ROOT / incident / filename).read_text(encoding="utf-8"))
            if incident == "INC-004" and filename == "metrics.json":
                assert before[0]["summary"] == (
                    "Shipping HTTP 5xx rate reached 12 percent; log source has no records")
                assert after[0]["summary"] == "Shipping HTTP 5xx rate reached 12 percent"
                assert before[0] == dict(after[0], summary=before[0]["summary"])
            else:
                assert after == before


def test_v2_partial_evidence_keeps_empty_tool_states_separate(manager):
    ctx = context(service_name="shipping-service", anchor_time="2026-09-01T13:05:00+08:00")
    results = {name: call(manager, name, ctx) for name in TOOLS}
    bundle = EvidenceBundle.from_results(ctx, results)
    assert {name: state.status for name, state in bundle.tool_status.items()} == {
        "query_logs": "empty", "query_metrics": "ok", "query_deployments": "empty"}
    assert len(bundle.evidence) == 1
    metric = bundle.evidence[0]
    assert metric.evidence_id == "rootlens-demo:v2:INC-004:metric:M401"
    assert metric.source_type == "metric" and metric.attributes.value == 12.0
    assert metric.summary == "Shipping HTTP 5xx rate reached 12 percent"
    assert "log" not in metric.summary.lower()


def test_v3_suite_changes_evidence_ids_not_expected_labels():
    evaluation = DEFAULT_RUNTIME_ROOT.parents[2] / "evaluation"
    previous = load_rootlens_cases(evaluation / "stage3-v2.json")
    current = load_rootlens_cases(evaluation / "stage3-v3.json")
    assert suite_fingerprint(previous) != suite_fingerprint(current)
    assert [case.case_id for case in previous] == [case.case_id for case in current]
    for before, after in zip(previous, current):
        assert before.runtime_inputs() == after.runtime_inputs()
        expected = before.expected.model_dump()
        expected["evidence_ids"] = ([item.replace("rootlens-demo:v1:", "rootlens-demo:v2:")
                                    for item in expected["evidence_ids"]]
                                   if expected["evidence_ids"] is not None else None)
        assert after.expected.model_dump() == expected
