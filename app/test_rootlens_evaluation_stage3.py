"""Stage 3-1 contract and metric tests; no paid model calls."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from core.evidence import EvidenceBundle, QueryContext
from core.routing_signals import extract_routing_signals
from evaluation.rootlens_cases import (
    EvaluationCase, EvaluationObservation, ExpectedResult, load_rootlens_cases,
)
from evaluation.rootlens_metrics import score_cases
from mcp.incident_tools import IncidentTools
from mcp.tool_manager import ToolResult


def example(case_id="one", **expected):
    return EvaluationCase(case_id=case_id, message="question",
                          expected=ExpectedResult(**expected))


def observe(case_id="one", **values):
    return EvaluationObservation(case_id=case_id, **values)


def test_case_requires_one_input_form_and_aware_time():
    with pytest.raises(ValidationError):
        EvaluationCase(case_id="x", expected=ExpectedResult())
    with pytest.raises(ValidationError):
        EvaluationCase(case_id="x", message="a", messages=["b"], expected=ExpectedResult())
    with pytest.raises(ValidationError):
        EvaluationCase(case_id="x", message="a", anchor_time="2026-09-01T10:05:00",
                       expected=ExpectedResult())
    case = EvaluationCase(case_id="x", messages=["a", "b"], expected=ExpectedResult())
    assert [item.message for item in case.runtime_inputs()] == ["a", "b"]


def test_optional_expectations_are_not_metric_failures():
    result = score_cases([example()], [observe()])
    assert all(metric.denominator == 0 and metric.value is None for metric in result.values())


def test_runtime_projection_never_exposes_expected_labels():
    case = EvaluationCase(case_id="x", message="payment-service 10:05 5xx",
                          environment="demo", expected=ExpectedResult(
                              intent="PRIVATE-SENTINEL", runbook_ids=["PRIVATE-RUNBOOK"]))
    projected = case.runtime_inputs()[0].model_dump(mode="json")
    assert set(projected) == {"message", "environment", "anchor_time"}
    assert "PRIVATE" not in str(projected)
    assert "PRIVATE" not in str(case.runtime_inputs())


def test_intent_accuracy_macro_f1_and_missing_prediction():
    cases = [example("a", intent="service_incident"),
             example("b", intent="resource_issue")]
    scores = score_cases(cases, [observe("a", intent="service_incident"),
                                 observe("b", intent="service_incident")])
    assert scores["intent_accuracy"].value == 0.5
    assert scores["intent_macro_f1"].value == pytest.approx(1 / 3)
    missing = score_cases(cases, [observe("a", intent="service_incident")])
    assert missing["intent_accuracy"].denominator == 2
    assert missing["intent_accuracy"].value == 0.5


def test_primary_and_supporting_exact_partial_with_explicit_empty_set():
    cases = [example("a", primary_agent="application",
                     supporting_agents=["database", "infrastructure"]),
             example("b", primary_agent="infrastructure", supporting_agents=[])]
    actual = [observe("a", primary_agent="application", supporting_agents=["database"]),
              observe("b", primary_agent="application", supporting_agents=[])]
    scores = score_cases(cases, actual)
    assert scores["primary_agent_accuracy"].value == 0.5
    assert scores["supporting_agent_exact_match"].value == 0.5
    assert scores["supporting_agent_partial_match"].value == 0.75


def test_evidence_coverage_uses_required_ids_only():
    scores = score_cases([example(evidence_ids=["E-1", "E-2"])],
                         [observe(evidence_ids=["E-1", "EXTRA"])])
    assert scores["evidence_required_coverage"].numerator == 1
    assert scores["evidence_required_coverage"].denominator == 2
    assert scores["evidence_required_coverage"].value == 0.5


def test_tool_status_empty_map_means_no_tools_and_failed_is_not_empty():
    cases = [example("a", tool_status={}),
             example("b", tool_status={"query_logs": "empty"})]
    result = score_cases(cases, [
        observe("a", tool_status={}),
        observe("b", tool_status={"query_logs": "failed"}),
    ])
    assert result["tool_status_accuracy"].denominator == 2
    assert result["tool_status_accuracy"].value == 0.5
    wrong = score_cases([cases[0]], [observe("a", tool_status={"query_logs": "ok"})])
    assert wrong["tool_status_accuracy"].value == 0


def test_clarification_and_structured_runbook_id_metrics():
    cases = [example("a", clarification_required=True, runbook_ids=["RL-RB-DB-001"]),
             example("b", clarification_required=False)]
    results = score_cases(cases, [
        observe("a", clarification_required=True, runbook_ids=["RL-RB-APP-001"],
                response="RL-RB-DB-001 is written in text"),
        observe("b", clarification_required=False),
    ])
    assert results["clarification_accuracy"].value == 1
    assert results["runbook_hit_accuracy"].denominator == 1
    assert results["runbook_hit_accuracy"].value == 0


def test_forbidden_claim_literal_count_and_unscored_diagnosis_points():
    case = example(forbidden_claims=["deployment definitely caused", "known root cause"],
                   diagnosis_points=["connection pool saturation"])
    result = score_cases([case], [
        observe(response="Deployment definitely caused the incident; needs review")])
    assert result["forbidden_claim_violation_count"].numerator == 1
    assert result["forbidden_claim_violation_count"].denominator == 2
    assert result["forbidden_claim_violation_count"].value == 1
    assert "diagnosis_points" not in result


def test_duplicate_and_unknown_observations_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        score_cases([example()], [observe(), observe()])
    with pytest.raises(ValueError, match="no matching"):
        score_cases([example()], [observe("other")])


def test_rootlens_suite_has_no_customer_defaults_and_unique_ids():
    cases = load_rootlens_cases()
    assert len(cases) == 6
    assert {case.case_id for case in cases} == {
        "INC-001", "INC-002", "INC-003", "INC-004-partial",
        "runbook-db-pool", "clarify-missing-service",
    }
    assert all(case.expected.intent not in {"refund", "invoice", "payment_issue"}
               for case in cases)
    assert all(not hasattr(item, "expected") for case in cases
               for item in case.runtime_inputs())


def bundle_for_case(case, tools):
    query = QueryContext.build(
        service_name=case.message.split()[0], environment=case.environment,
        anchor_time=case.anchor_time, timezone=tools.manifest.timezone,
        dataset_id=tools.manifest.dataset_id,
        dataset_version=tools.manifest.dataset_version,
    )

    async def acquire():
        return {
            name: ToolResult(
                success=True, tool_name=name,
                data=await getattr(tools, name)(query.tool_params(name)),
            )
            for name in ("query_logs", "query_metrics", "query_deployments")
        }

    return EvidenceBundle.from_results(query, asyncio.run(acquire()))


@pytest.mark.parametrize("case_id", ["INC-001", "INC-002", "INC-003", "INC-004-partial"])
def test_synthetic_cases_have_real_scoped_runtime_records(case_id):
    cases = {case.case_id: case for case in load_rootlens_cases()}
    case = cases[case_id]
    assert case.environment == "demo"
    tools = IncidentTools()
    assert tools.manifest.simulated
    bundle = bundle_for_case(case, tools)
    assert set(case.expected.evidence_ids) <= {item.evidence_id for item in bundle.evidence}
    assert {name: state.status for name, state in bundle.tool_status.items()} == (
        case.expected.tool_status)
    if case_id == "INC-002":
        assert "database" not in extract_routing_signals(bundle).floors
    if case_id == "INC-003":
        assert "infrastructure" in extract_routing_signals(bundle).floors
    if case_id == "INC-004-partial":
        assert {item.source_type for item in bundle.evidence} == {"metric"}


def test_changed_expected_file_cannot_change_runtime_query(tmp_path):
    case = next(item for item in load_rootlens_cases() if item.case_id == "INC-002")
    tools = IncidentTools()
    first = bundle_for_case(case, tools)
    private = tmp_path / "evaluation" / "INC-002.expected.json"
    private.parent.mkdir()
    private.write_text('{"expected_diagnosis":"PRIVATE-A"}', encoding="utf-8")
    private.write_text('{"expected_diagnosis":"PRIVATE-B"}', encoding="utf-8")
    second = bundle_for_case(case, tools)
    assert [item.evidence_id for item in first.evidence] == [
        item.evidence_id for item in second.evidence]
    with pytest.raises(ValueError):
        tools.resolve_raw_ref("../evaluation/INC-002.expected.json#L201")


def test_structured_knowledge_sources_are_not_parsed_from_prompt(monkeypatch):
    from api import main

    item = {"document_id": "RL-RB-DB-001", "chunk_id": "RL-RB-DB-001:c0000",
            "source_ref": "knowledge/rootlens/db-connection-pool.md",
            "title": "DB pool runbook", "content": "Check pool saturation"}
    fake = SimpleNamespace(search_with_rewrite=AsyncMock(return_value=ToolResult(
        success=True, data=[item], tool_name="knowledge_search",
        rewrite_status="skipped", retrieval_status="performed", rerank_status="skipped")))
    monkeypatch.setattr(main, "_tool_manager", fake)
    result = asyncio.run(main._retrieve_knowledge_context("pool"))
    assert result.used
    assert result.sources[0].document_id == "RL-RB-DB-001"
    assert result.sources[0].chunk_id == "RL-RB-DB-001:c0000"
    assert result.sources[0].source_ref == item["source_ref"]
    assert "Check pool saturation" in result.text


def test_fallback_knowledge_has_no_structured_source(monkeypatch):
    from api import main

    fake = SimpleNamespace(search_with_rewrite=AsyncMock(return_value=ToolResult(
        success=True, data=[{"fallback": True, "document_id": "RL-RB-DB-001",
                             "chunk_id": "RL-RB-DB-001:c0000", "source_ref": "fake",
                             "content": "fallback"}], tool_name="knowledge_search",
        rewrite_status="failed", retrieval_status="degraded", rerank_status="skipped")))
    monkeypatch.setattr(main, "_tool_manager", fake)
    result = asyncio.run(main._retrieve_knowledge_context("pool"))
    assert not result.used and not result.sources
