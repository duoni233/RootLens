"""Offline Stage 4-2 integration checks; no live model or Chroma calls."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.agent_orchestrator import (
    AgentOrchestrator, AgentResponse, AgentType, Request,
)
from core.diagnosis_assembler import DiagnosisAssembler
from core.diagnosis_pipeline import (
    DiagnosisPipeline, KnowledgeResult, KnowledgeSource,
)
from core.incident_diagnosis import DiagnosisBuildStatus
from core.intent_recognizer import IntentCategory, IntentResult, UrgencyLevel
from mcp.incident_tools import IncidentTools
from mcp.tool_manager import MCPToolManager
from mcp.tool_manager import ToolResult


MESSAGE = "payment-service 10:05 开始 5xx 激增"


def intent(category=IntentCategory.SERVICE_INCIDENT, entities=None):
    return IntentResult(
        intent=category, confidence=0.9, urgency=UrgencyLevel.MEDIUM,
        intent_group="application", entities=entities if entities is not None else {
            "service_name": ["payment-service"], "start_time": ["10:05"],
            "status_code": ["5xx"],
        }, reasoning="offline", latency_ms=1.0,
    )


def synthesis(evidence_ids=(), **changes):
    data = {
        "summary": "现场显示服务出现异常，根因仍需验证。",
        "confirmed_findings": ([{"statement": "服务返回 5xx。",
                                "evidence_ids": [evidence_ids[0]]}]
                               if evidence_ids else []),
        "hypotheses": [], "recommended_actions": [], "evidence_gaps": [],
    }
    data.update(changes)
    return data


def fake_model(output=None, *, error=None):
    async def create(**kwargs):
        if error:
            raise error
        prompt = kwargs["messages"][0]["content"]
        runtime = json.loads(prompt.split("本次输入：\n", 1)[1])
        ids = [item["evidence_id"] for item in runtime["operational_evidence"]]
        result = output(ids) if callable(output) else (output or synthesis(ids))
        return SimpleNamespace(stop_reason="end_turn", content=[
            {"type": "text", "text": result if isinstance(result, str)
             else json.dumps(result, ensure_ascii=False)},
        ])
    return SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=create)))


def make_pipeline(model=None, *, agent_reply="原来的 Markdown 回复"):
    tools = IncidentTools()
    manager = MCPToolManager(api_key="offline", base_url="https://example.invalid")
    tools.register(manager, cache_ttl=0)
    orchestrator = AgentOrchestrator(api_key="offline", base_url="https://example.invalid")

    async def execute(request, agent_type):
        return AgentResponse(agent_type=agent_type, content=agent_reply, success=True)

    orchestrator._execute = execute

    async def lookup(query):
        return KnowledgeResult(
            text="连接池 Runbook：先检查指标，再验证假设。", used=True,
            stages={"rewrite": "performed", "retrieval": "performed", "rerank": "skipped"},
            sources=[KnowledgeSource(
                document_id="RL-RB-DB-001", chunk_id="RL-RB-DB-001:c0000",
                source_ref="knowledge/rootlens/db-connection-pool.md", source_type="runbook")],
        )

    client = model or fake_model()
    pipeline = DiagnosisPipeline(
        orchestrator=orchestrator, tool_manager=manager, knowledge_lookup=lookup,
        dataset_id=tools.manifest.dataset_id, dataset_version=tools.manifest.dataset_version,
        timezone=tools.manifest.timezone, assembler=DiagnosisAssembler(client, "fake-model"),
    )
    return pipeline, orchestrator, client


def run_pipeline(pipeline, *, message=MESSAGE, recognized=None, **kwargs):
    return asyncio.run(pipeline.run(
        message=message, user_id="u", conv_id="c", memory_context="", history=None,
        intent_result=recognized or intent(), **kwargs,
    ))


def test_diagnosis_pipeline_builds_structure_without_replacing_markdown():
    pipeline, _, client = make_pipeline()
    outcome = run_pipeline(pipeline)
    build = outcome.diagnosis_build_result
    assert build.status == DiagnosisBuildStatus.SUCCESS
    assert outcome.result.response == "[application - 主处理]\n原来的 Markdown 回复\n\n" \
                                      "[database - 辅助处理]\n原来的 Markdown 回复"
    assert build.diagnosis.primary_agent == "application"
    assert build.diagnosis.supporting_agents == ["database"]
    assert {ref.evidence_id for ref in build.diagnosis.evidence_refs} == {
        item.evidence_id for item in outcome.bundle.evidence}
    assert build.diagnosis.knowledge_refs[0].document_id == "RL-RB-DB-001"
    assert len(outcome.result.agent_executions) == 2
    assert client.messages.create.await_count == 1


def test_model_cannot_override_program_owned_fields():
    malicious = synthesis()
    malicious["primary_agent"] = "database"
    pipeline, _, _ = make_pipeline(fake_model(malicious))
    outcome = run_pipeline(pipeline)
    assert outcome.diagnosis_build_result.status == DiagnosisBuildStatus.VALIDATION_FAILED
    assert outcome.result.primary_agent == AgentType.APPLICATION


@pytest.mark.parametrize("bad", ["not JSON", {"summary": "x", "unknown": "field"}])
def test_bad_model_output_fails_closed(bad):
    pipeline, _, _ = make_pipeline(fake_model(bad))
    outcome = run_pipeline(pipeline)
    assert outcome.diagnosis_build_result.diagnosis is None
    assert outcome.diagnosis_build_result.status in {
        DiagnosisBuildStatus.PARSE_FAILED, DiagnosisBuildStatus.VALIDATION_FAILED}
    assert "原来的 Markdown 回复" in outcome.result.response


def test_api_exception_fails_closed():
    pipeline, _, _ = make_pipeline(fake_model(error=RuntimeError("offline")))
    outcome = run_pipeline(pipeline)
    assert outcome.diagnosis_build_result.status == DiagnosisBuildStatus.ASSEMBLER_FAILED
    assert "原来的 Markdown 回复" in outcome.result.response


def test_unknown_finding_evidence_is_rejected():
    model = fake_model(lambda ids: synthesis(ids, confirmed_findings=[{
        "statement": "编造的观察", "evidence_ids": ["FAKE"]}]))
    pipeline, _, _ = make_pipeline(model)
    outcome = run_pipeline(pipeline)
    assert outcome.diagnosis_build_result.status == DiagnosisBuildStatus.VALIDATION_FAILED


def test_high_risk_action_cannot_be_marked_low():
    model = fake_model(lambda ids: synthesis(ids, recommended_actions=[{
        "action": "rollback production", "reason": "test", "risk_level": "low",
        "requires_approval": False, "related_evidence_ids": []}]))
    pipeline, _, _ = make_pipeline(model)
    assert run_pipeline(pipeline).diagnosis_build_result.status == \
        DiagnosisBuildStatus.VALIDATION_FAILED


def test_duplicate_findings_are_deduplicated():
    model = fake_model(lambda ids: synthesis(ids, confirmed_findings=[{
        "statement": "5xx 已出现", "evidence_ids": [ids[0]]}, {
        "statement": "5xx 已出现", "evidence_ids": [ids[0]]}]))
    pipeline, _, _ = make_pipeline(model)
    diagnosis = run_pipeline(pipeline).diagnosis_build_result.diagnosis
    assert diagnosis is not None and len(diagnosis.confirmed_findings) == 1


def test_query_context_clarification_skips_model():
    pipeline, orchestrator, client = make_pipeline()
    orchestrator._execute = AsyncMock(side_effect=AssertionError("must not run"))
    outcome = run_pipeline(pipeline, recognized=intent(entities={"start_time": ["10:05"]}))
    assert outcome.clarification_required
    assert outcome.diagnosis_build_result.status == DiagnosisBuildStatus.SUCCESS
    assert outcome.diagnosis_build_result.diagnosis.status == "clarification"
    client.messages.create.assert_not_awaited()


def test_runbook_only_has_knowledge_but_no_operational_findings():
    pipeline, _, _ = make_pipeline(fake_model(synthesis()))
    outcome = run_pipeline(
        pipeline, message="查连接池 Runbook",
        recognized=intent(IntentCategory.RUNBOOK_QUERY, entities={}),
    )
    assert outcome.bundle is None
    diagnosis = outcome.diagnosis_build_result.diagnosis
    assert diagnosis.status == "runbook"
    assert diagnosis.evidence_refs == [] and diagnosis.confirmed_findings == []
    assert diagnosis.knowledge_refs[0].document_id == "RL-RB-DB-001"


def test_eval_can_skip_structure_and_model_call():
    pipeline, _, client = make_pipeline()
    outcome = run_pipeline(pipeline, build_diagnosis=False)
    assert outcome.diagnosis_build_result.status == DiagnosisBuildStatus.NOT_RUN
    client.messages.create.assert_not_awaited()


def test_real_execute_records_failure_then_fallback_without_losing_reply():
    orchestrator = AgentOrchestrator(api_key="offline", base_url="https://example.invalid")
    async def fail(request):
        return AgentResponse(AgentType.APPLICATION, "failed", False)
    async def fallback(request):
        return AgentResponse(AgentType.GENERAL, "fallback text", True)
    orchestrator._pool[AgentType.APPLICATION][0].handle = fail
    orchestrator._pool[AgentType.GENERAL][0].handle = fallback
    request = Request(message=MESSAGE, user_id="u", conv_id="c",
                      intent=IntentCategory.SERVICE_INCIDENT)
    result = asyncio.run(orchestrator.run(request))
    assert result.response == "fallback text"
    assert [(r.requested_agent, r.executed_agent, r.success) for r in result.agent_executions] == [
        (AgentType.APPLICATION, AgentType.APPLICATION, False),
        (AgentType.APPLICATION, AgentType.GENERAL, True),
    ]
    assert all(r.degraded for r in result.agent_executions)


def test_parallel_supporting_failure_marks_degraded_and_keeps_primary_reply():
    pipeline, orchestrator, _ = make_pipeline()

    async def execute(request, agent_type):
        if agent_type == AgentType.DATABASE:
            return AgentResponse(agent_type, "database failed", False)
        return AgentResponse(agent_type, "application succeeded", True)

    orchestrator._execute = execute
    outcome = run_pipeline(pipeline)
    assert outcome.result.response == "[application - 主处理]\napplication succeeded"
    assert [(r.role, r.success) for r in outcome.result.agent_executions] == [
        ("primary", True), ("supporting", False)]
    diagnosis = outcome.diagnosis_build_result.diagnosis
    assert diagnosis is not None and diagnosis.degraded
    assert any("辅助 Agent" in gap.description for gap in diagnosis.evidence_gaps)


def test_empty_tool_is_not_degraded_but_failed_tool_is():
    pipeline, _, _ = make_pipeline()
    original = pipeline.tools.call

    async def empty_logs(name, params):
        if name == "query_logs":
            return ToolResult(success=True, data=[], tool_name=name)
        return await original(name, params)

    pipeline.tools.call = empty_logs
    empty = run_pipeline(pipeline)
    assert empty.bundle.tool_status["query_logs"].status == "empty"
    assert empty.diagnosis_build_result.diagnosis.degraded is False

    async def failed_logs(name, params):
        if name == "query_logs":
            return ToolResult(success=False, data=None, tool_name=name, error="offline")
        return await original(name, params)

    pipeline.tools.call = failed_logs
    failed = run_pipeline(pipeline)
    assert failed.bundle.tool_status["query_logs"].status == "failed"
    assert failed.diagnosis_build_result.diagnosis.degraded is True


def test_orchestrator_clarification_skips_model():
    pipeline, orchestrator, client = make_pipeline()
    orchestrator._execute = AsyncMock(side_effect=AssertionError("must not run"))
    unclear = intent(IntentCategory.OTHER, entities={})
    unclear.confidence = 0.1
    outcome = run_pipeline(pipeline, message="不知道哪里出了问题", recognized=unclear)
    assert outcome.clarification_required
    assert outcome.diagnosis_build_result.diagnosis.status == "clarification"
    orchestrator._execute.assert_not_awaited()
    client.messages.create.assert_not_awaited()


def test_semantic_unknown_knowledge_id_is_not_accepted_as_structure():
    malicious = synthesis()
    malicious["knowledge_refs"] = [{"document_id": "FAKE", "chunk_id": "x",
                                    "source_ref": "x"}]
    pipeline, _, _ = make_pipeline(fake_model(malicious))
    assert run_pipeline(pipeline).diagnosis_build_result.status == \
        DiagnosisBuildStatus.VALIDATION_FAILED
