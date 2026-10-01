"""Stage 3-2 evaluation through the shared diagnosis core, without paid calls."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from agents.agent_orchestrator import AgentOrchestrator, AgentResponse, AgentType
from core.diagnosis_pipeline import DiagnosisPipeline, KnowledgeResult, KnowledgeSource
from core.intent_recognizer import IntentCategory
from evaluation.rootlens_cases import EvaluationCase, ExpectedResult, load_rootlens_cases
from evaluation.rootlens_evaluator import RootLensEvaluator
from mcp.incident_tools import IncidentTools
from mcp.tool_manager import MCPToolManager


@pytest.fixture
def evaluation_runtime(monkeypatch):
    tools = IncidentTools()
    manager = MCPToolManager(api_key="offline-test-key", base_url="https://example.invalid")
    tools.register(manager, cache_ttl=0)
    orchestrator = AgentOrchestrator(
        api_key="offline-test-key", base_url="https://example.invalid")
    recognizer = orchestrator._intent_recognizer
    recognizer._embedding_enabled = False
    recognizer_calls = []
    original_recognize = recognizer.recognize

    async def recognize(message, history=None):
        recognizer_calls.append((message, history))
        return await original_recognize(message, history=history)

    async def llm_intent(message, history):
        if "Runbook" in message:
            intent = IntentCategory.RUNBOOK_QUERY
        elif "CPU" in message:
            intent = IntentCategory.RESOURCE_ISSUE
        else:
            intent = IntentCategory.SERVICE_INCIDENT
        return {"intent": intent, "confidence": 0.99, "reasoning": "offline test double"}

    monkeypatch.setattr(recognizer, "recognize", recognize)
    monkeypatch.setattr(recognizer, "_llm_recognize", llm_intent)
    agent_requests = []

    async def execute(request, agent_type):
        agent_requests.append((request, agent_type))
        return AgentResponse(
            agent_type=agent_type,
            content="根据现场记录初步分析；发布先于异常不证明因果，需继续验证。",
            success=True,
        )

    monkeypatch.setattr(orchestrator, "_execute", execute)
    knowledge_queries = []

    async def knowledge_lookup(query):
        knowledge_queries.append(query)
        if "DBConnectionError" in query or "连接池" in query:
            document_id = "RL-RB-DB-001"
        elif "checkout-service" in query:
            document_id = "RL-RB-APP-001"
        else:
            return KnowledgeResult(stages={
                "rewrite": "skipped", "retrieval": "performed", "rerank": "skipped",
            })
        return KnowledgeResult(
            text=f"Runbook {document_id}",
            used=True,
            sources=[KnowledgeSource(
                document_id=document_id, chunk_id=f"{document_id}:c0000",
                source_ref=f"knowledge/rootlens/{document_id}.md",
                source_type="runbook",
            )],
            stages={"rewrite": "skipped", "retrieval": "performed", "rerank": "skipped"},
        )

    pipeline = DiagnosisPipeline(
        orchestrator=orchestrator, tool_manager=manager,
        knowledge_lookup=knowledge_lookup,
        dataset_id=tools.manifest.dataset_id,
        dataset_version=tools.manifest.dataset_version,
        timezone=tools.manifest.timezone,
    )
    return {
        "evaluator": RootLensEvaluator(orchestrator=orchestrator, pipeline=pipeline),
        "orchestrator": orchestrator,
        "pipeline": pipeline,
        "manager": manager,
        "recognizer_calls": recognizer_calls,
        "agent_requests": agent_requests,
        "knowledge_queries": knowledge_queries,
    }


def evaluate(runtime, cases=None):
    return asyncio.run(runtime["evaluator"].run(cases or load_rootlens_cases()))


def test_six_cases_use_intent_recognizer_and_pipeline_with_real_evidence(
        evaluation_runtime, monkeypatch):
    runtime = evaluation_runtime
    original_run = runtime["pipeline"].run
    pipeline_calls = []

    async def counted_run(**kwargs):
        pipeline_calls.append(kwargs)
        return await original_run(**kwargs)

    monkeypatch.setattr(runtime["pipeline"], "run", counted_run)
    report = evaluate(runtime)
    observations = {item.case_id: item for item in report.observations}
    assert len(runtime["recognizer_calls"]) == len(pipeline_calls) == 6
    assert set(observations) == {item.case_id for item in load_rootlens_cases()}
    assert report.judge_status == "not_run"

    incident = observations["INC-001"]
    assert incident.intent == "service_incident"
    assert incident.primary_agent == "application"
    assert incident.supporting_agents == ["database"]
    assert "rootlens-demo:v1:INC-001:log:L001" in incident.evidence_ids
    assert incident.tool_status == {name: "ok" for name in (
        "query_logs", "query_metrics", "query_deployments")}
    assert incident.runbook_ids == ["RL-RB-DB-001"]
    assert incident.knowledge_document_ids == ["RL-RB-DB-001"]
    assert incident.rag_stage_status["retrieval"] == "performed"
    assert "发布先于异常不证明因果" in incident.response

    app_only = observations["INC-002"]
    assert app_only.primary_agent == "application"
    assert app_only.supporting_agents == []
    assert app_only.runbook_ids == ["RL-RB-APP-001"]
    assert app_only.tool_status["query_deployments"] == "empty"

    resource = observations["INC-003"]
    assert resource.intent == "resource_issue"
    assert resource.primary_agent == "infrastructure"
    assert resource.supporting_agents == []
    assert "rootlens-demo:v1:INC-003:metric:M301" in resource.evidence_ids

    runbook = observations["runbook-db-pool"]
    assert runbook.tool_status == {}
    assert runbook.evidence_ids == []
    assert runbook.runbook_ids == ["RL-RB-DB-001"]
    clarification = observations["clarify-missing-service"]
    assert clarification.clarification_required
    assert clarification.primary_agent is None
    assert clarification.tool_status == {}
    clarification_identity = pipeline_calls[4]["conv_id"]
    assert all(request.conv_id != clarification_identity
               for request, _ in runtime["agent_requests"])

    partial = observations["INC-004-partial"]
    assert partial.tool_status == {
        "query_logs": "empty", "query_metrics": "ok",
        "query_deployments": "empty",
    }
    assert partial.evidence_types == ["metric"]
    assert partial.evidence_ids == ["rootlens-demo:v1:INC-004:metric:M401"]
    assert all(call["memory_context"] == "" for call in pipeline_calls)


def test_default_suite_metric_numerators_denominators(evaluation_runtime):
    report = evaluate(evaluation_runtime)
    metrics = report.to_dict()["metrics"]
    assert metrics["intent_accuracy"] == {
        "numerator": 6, "denominator": 6, "value": 1.0}
    assert metrics["intent_macro_f1"]["denominator"] == 3
    assert metrics["primary_agent_accuracy"]["denominator"] == 4
    assert metrics["supporting_agent_exact_match"]["denominator"] == 4
    assert metrics["supporting_agent_partial_match"]["denominator"] == 4
    assert metrics["evidence_required_coverage"]["denominator"] == 9
    assert metrics["tool_status_accuracy"]["denominator"] == 6
    assert metrics["clarification_accuracy"]["denominator"] == 6
    assert metrics["runbook_hit_accuracy"]["denominator"] == 3
    assert metrics["forbidden_claim_violation_count"]["value"] == 0
    assert all(value["value"] == 1.0 for name, value in metrics.items()
               if name != "forbidden_claim_violation_count")


def test_expected_is_not_passed_to_recognizer_pipeline_tools_or_agent(
        evaluation_runtime, monkeypatch):
    runtime = evaluation_runtime
    sentinel = "PRIVATE-EXPECTED-SENTINEL"
    case = EvaluationCase(
        case_id="private", message="payment-service 10:05 5xx 激增",
        expected=ExpectedResult(intent=sentinel, diagnosis_points=[sentinel]),
    )
    tool_calls = []
    original_call = runtime["manager"].call

    async def capture_tool(name, params, *args, **kwargs):
        tool_calls.append((name, params))
        return await original_call(name, params, *args, **kwargs)

    monkeypatch.setattr(runtime["manager"], "call", capture_tool)
    report = evaluate(runtime, [case])
    assert report.metrics["intent_accuracy"].value == 0
    assert sentinel not in str(runtime["recognizer_calls"])
    assert sentinel not in str(tool_calls)
    assert sentinel not in str(runtime["knowledge_queries"])
    assert sentinel not in str(runtime["agent_requests"])
    assert all(request.user_id.startswith("eval:") and request.context.find(sentinel) == -1
               for request, _ in runtime["agent_requests"])


def test_multiturn_history_is_case_local_and_never_reads_redis(
        evaluation_runtime, monkeypatch):
    runtime = evaluation_runtime
    cases = [
        EvaluationCase(case_id="multi", messages=[
            "payment-service 10:05 5xx 激增",
            "payment-service 10:05 仍有 5xx 激增",
        ], expected=ExpectedResult()),
        EvaluationCase(case_id="next", message="checkout-service 11:10 5xx 激增",
                       expected=ExpectedResult()),
    ]
    original_run = runtime["pipeline"].run
    calls = []

    async def capture(**kwargs):
        calls.append(kwargs)
        return await original_run(**kwargs)

    monkeypatch.setattr(runtime["pipeline"], "run", capture)
    report = evaluate(runtime, cases)
    assert len(report.observations) == 2 and len(calls) == 3
    assert calls[0]["history"] is None
    assert calls[1]["history"][0]["content"] == cases[0].messages[0]
    assert calls[2]["history"] is None
    assert calls[0]["conv_id"] == calls[1]["conv_id"] != calls[2]["conv_id"]
    assert all(call["memory_context"] == "" for call in calls)


def test_runbook_query_never_calls_operational_tools(evaluation_runtime, monkeypatch):
    runtime = evaluation_runtime
    call = AsyncMock(side_effect=AssertionError("operational tools must not run"))
    monkeypatch.setattr(runtime["manager"], "call", call)
    case = next(item for item in load_rootlens_cases() if item.case_id == "runbook-db-pool")
    observation = evaluate(runtime, [case]).observations[0]
    assert observation.runbook_ids == ["RL-RB-DB-001"]
    call.assert_not_awaited()


def test_clarification_never_executes_agent(evaluation_runtime):
    runtime = evaluation_runtime
    case = next(item for item in load_rootlens_cases()
                if item.case_id == "clarify-missing-service")
    observation = evaluate(runtime, [case]).observations[0]
    assert observation.clarification_required
    assert not runtime["agent_requests"]
    assert not runtime["knowledge_queries"]


def test_http_default_uses_rootlens_not_legacy_judge_or_baseline(
        evaluation_runtime, monkeypatch):
    from api import main

    monkeypatch.setattr(main, "_rootlens_evaluator", evaluation_runtime["evaluator"])
    legacy = AsyncMock(side_effect=AssertionError("legacy Judge must not run"))
    monkeypatch.setattr(main, "_evaluator", type("Legacy", (), {"run": legacy})())

    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                    base_url="http://test") as client:
            return await client.post("/eval/run")

    response = asyncio.run(request())
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "rootlens_deterministic"
    assert body["total"] == 6 and body["judge_status"] == "not_run"
    assert body["metrics"]["evidence_required_coverage"]["denominator"] == 9
    assert len(body["observations"]) == 6
    legacy.assert_not_awaited()


def test_http_rejects_legacy_fields_without_explicit_mode(evaluation_runtime, monkeypatch):
    from api import main

    monkeypatch.setattr(main, "_rootlens_evaluator", evaluation_runtime["evaluator"])

    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                    base_url="http://test") as client:
            return await client.post("/eval/run", json={"intent_cases": [
                {"message": "refund", "expected_intent": "refund"}]})

    assert asyncio.run(request()).status_code == 400


def test_labels_remain_outside_image_and_compose_mounts_read_only():
    app_root = Path(__file__).parent
    assert "datasets/evaluation/" in (app_root / ".dockerignore").read_text(encoding="utf-8")
    compose = (app_root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "./datasets/evaluation/stage3-v1.json:/eval-data/stage3-v1.json:ro" in compose
