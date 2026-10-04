"""Offline execution-trace checks; never call a paid model or live service."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agents.agent_orchestrator import AgentOrchestrator, AgentResponse, AgentType
from core.diagnosis_entry import run_diagnosis
from core.diagnosis_trace import (
    TraceRecorder, activate_trace, begin_step, finish_step, reset_trace,
)
from core.intent_recognizer import IntentCategory
from mcp.tool_manager import MCPToolManager, Tool, ToolResult
from test_rootlens_stage4_assembler import (
    MESSAGE, fake_model, intent, make_pipeline, runbook_synthesis, synthesis,
)


def run_traced(pipeline, orchestrator, *, recognized=None, message=MESSAGE,
               build_diagnosis=True):
    orchestrator.recognize_intent = AsyncMock(return_value=recognized or intent())
    return asyncio.run(run_diagnosis(
        orchestrator=orchestrator, pipeline=pipeline, message=message,
        user_id="offline", conv_id="offline", build_diagnosis=build_diagnosis,
    ))


def use_real_attempts(orchestrator):
    orchestrator._execute = AgentOrchestrator._execute.__get__(orchestrator)
    for agent_type, agents in orchestrator._pool.items():
        for agent in agents:
            async def handle(req, selected=agent_type):
                return AgentResponse(selected, "safe diagnosis", True, latency_ms=1.0)
            agent.handle = handle


def steps(trace, kind):
    return [step for step in trace.steps if step.step_type == kind]


def test_multi_agent_trace_has_independent_tools_and_real_attempts():
    pipeline, orchestrator, _ = make_pipeline()
    use_real_attempts(orchestrator)
    diagnosis = run_traced(pipeline, orchestrator)
    outcome, trace = diagnosis.outcome, diagnosis.outcome.trace
    assert trace.schema_version == "1" and trace.trace_id
    assert trace.request_id == outcome.result.request_id
    assert trace.started_at <= trace.completed_at
    assert trace.overall_status == "success" and not trace.degraded
    assert steps(trace, "intent_recognition")[0].metadata["intent"] == "service_incident"
    assert steps(trace, "query_context")[0].status == "success"
    assert steps(trace, "evidence_gate")[0].metadata["decision"] == "acquire"
    for name in ("query_logs", "query_metrics", "query_deployments"):
        tool_step = steps(trace, name)[0]
        assert tool_step.status == "success" and tool_step.result_kind == "items"
        assert tool_step.evidence_ids
        assert tool_step.metadata["record_count"] == len(tool_step.evidence_ids)
    assert {step.metadata["role"] for step in steps(trace, "agent_execution")} == {
        "primary", "supporting",
    }
    assert steps(trace, "routing")[0].metadata["primary_agent"] == "application"
    assert steps(trace, "routing")[0].metadata["supporting_agents"] == ["database"]
    assert steps(trace, "rag_retrieval")[0].knowledge_ids == ["RL-RB-DB-001:c0000"]
    assert steps(trace, "diagnosis_assembly")[0].status == "success"
    for step in trace.steps:
        assert step.started_at <= step.completed_at
        assert step.latency_ms >= 0
    # Steps are collected as observations. Agent/tool parallelism is interpreted by timestamps.
    assert len({step.step_id for step in trace.steps}) == len(trace.steps)


def test_runbook_trace_skips_operational_tools_and_keeps_rag():
    pipeline, orchestrator, _ = make_pipeline(fake_model(runbook_synthesis()))
    use_real_attempts(orchestrator)
    query = intent(IntentCategory.RUNBOOK_QUERY, {"service_name": ["payment-service"]})
    trace = run_traced(pipeline, orchestrator, recognized=query,
                       message="怎么处理 payment-service 连接池问题？").outcome.trace
    assert all(steps(trace, name)[0].status == "skipped" for name in (
        "query_logs", "query_metrics", "query_deployments"))
    assert steps(trace, "rag_retrieval")[0].status == "success"
    assert trace.overall_status == "success"


def test_empty_is_success_and_failed_tool_degrades_without_fabricated_evidence():
    pipeline, orchestrator, _ = make_pipeline()
    original = pipeline.tools.call

    async def changed(name, params):
        if name == "query_logs":
            return ToolResult(True, [], name)
        if name == "query_deployments":
            return ToolResult(False, None, name, error="offline failure")
        return await original(name, params)

    pipeline.tools.call = changed
    outcome = run_traced(pipeline, orchestrator).outcome
    trace = outcome.trace
    assert (steps(trace, "query_logs")[0].status,
            steps(trace, "query_logs")[0].result_kind) == ("success", "empty")
    assert steps(trace, "query_deployments")[0].status == "failed"
    assert steps(trace, "query_deployments")[0].error_code == "tool_unavailable"
    assert steps(trace, "query_metrics")[0].status == "success"
    assert all(item.source_type == "metric" for item in outcome.bundle.evidence)
    assert trace.overall_status == "degraded" and trace.degraded


def test_inc004_metric_and_empty_tool_states_keep_separate_sources():
    model = fake_model(lambda ids: synthesis(ids, confirmed_findings=[{
        "statement": "shipping-service HTTP 5xx rate reached 12 percent",
        "evidence_ids": ids,
    }], evidence_gaps=[{
        "description": "日志和发布查询未返回记录",
        "why_needed": "需要补充现场信息后才能判断原因",
    }]))
    pipeline, orchestrator, client = make_pipeline(model)
    recognized = intent(entities={"service_name": ["shipping-service"],
                                  "start_time": ["13:05"], "status_code": ["5xx"]})
    outcome = run_traced(pipeline, orchestrator, recognized=recognized,
                         message="shipping-service 13:05 开始 5xx 升高，帮我排查").outcome
    diagnosis, trace = outcome.diagnosis_build_result.diagnosis, outcome.trace
    assert diagnosis is not None and not diagnosis.degraded
    assert diagnosis.tool_status == {"query_logs": "empty", "query_metrics": "ok",
                                     "query_deployments": "empty"}
    assert len(diagnosis.confirmed_findings) == 1
    assert diagnosis.confirmed_findings[0].evidence_ids == [
        "rootlens-demo:v2:INC-004:metric:M401"]
    assert "log" not in diagnosis.confirmed_findings[0].statement.lower()
    for name in ("query_logs", "query_deployments"):
        step = steps(trace, name)[0]
        assert (step.status, step.result_kind, step.evidence_ids) == (
            "success", "empty", [])
    assert trace.overall_status == "success" and not trace.degraded
    prompt = client.messages.create.await_args.kwargs["messages"][0]["content"]
    payload = json.loads(prompt.split("本次输入：\n", 1)[1])
    assert payload["operational_evidence"] == [{
        "evidence_id": "rootlens-demo:v2:INC-004:metric:M401",
        "source_type": "metric",
        "summary": "Shipping HTTP 5xx rate reached 12 percent",
    }]
    assert payload["tool_status"] == diagnosis.tool_status


def test_degraded_tool_result_is_not_accepted_as_operational_evidence():
    pipeline, orchestrator, _ = make_pipeline()
    original = pipeline.tools.call

    async def changed(name, params):
        if name == "query_logs":
            return ToolResult(True, [{"summary": "invented fallback"}], name,
                              error="timeout", retrieval_status="degraded")
        return await original(name, params)

    pipeline.tools.call = changed
    outcome = run_traced(pipeline, orchestrator).outcome
    log_step = steps(outcome.trace, "query_logs")[0]
    assert log_step.status == "degraded" and log_step.evidence_ids == []
    assert log_step.metadata["fallback"] is True
    assert all(item.source_type != "log" for item in outcome.bundle.evidence)
    assert outcome.trace.overall_status == "degraded"


def test_three_tool_intervals_can_overlap_without_implying_array_order():
    pipeline, orchestrator, _ = make_pipeline()
    original = pipeline.tools.call

    async def delayed(name, params):
        await asyncio.sleep(0.02)
        return await original(name, params)

    pipeline.tools.call = delayed
    trace = run_traced(pipeline, orchestrator).outcome.trace
    tool_steps = [steps(trace, name)[0] for name in (
        "query_logs", "query_metrics", "query_deployments")]
    assert max(step.started_at for step in tool_steps) < min(
        step.completed_at for step in tool_steps)


def test_failed_agent_and_fallback_are_two_observable_attempts():
    pipeline, orchestrator, _ = make_pipeline()
    use_real_attempts(orchestrator)
    async def fail(req):
        return AgentResponse(AgentType.APPLICATION, "failed", False)
    async def fallback(req):
        return AgentResponse(AgentType.GENERAL, "fallback answer", True)
    orchestrator._pool[AgentType.APPLICATION][0].handle = fail
    orchestrator._pool[AgentType.GENERAL][0].handle = fallback
    outcome = run_traced(pipeline, orchestrator).outcome
    attempts = [step for step in steps(outcome.trace, "agent_execution")
                if step.metadata["requested_agent"] == "application"]
    assert [(step.metadata["executed_agent"], step.status) for step in attempts] == [
        ("application", "failed"), ("general_ops", "degraded"),
    ]
    assert len(outcome.result.agent_executions) >= 2
    assert outcome.trace.overall_status == "degraded"
    assert "fallback answer" in outcome.result.response


def test_supporting_failure_keeps_primary_and_is_visible():
    pipeline, orchestrator, _ = make_pipeline()
    use_real_attempts(orchestrator)
    async def fail(req):
        return AgentResponse(AgentType.DATABASE, "failed", False)
    orchestrator._pool[AgentType.DATABASE][0].handle = fail
    outcome = run_traced(pipeline, orchestrator).outcome
    assert any(step.status == "failed" and step.metadata["role"] == "supporting"
               for step in steps(outcome.trace, "agent_execution"))
    assert any(step.status == "success" and step.metadata["role"] == "primary"
               for step in steps(outcome.trace, "agent_execution"))
    assert outcome.trace.overall_status == "degraded"
    assert "application" in outcome.result.response


def test_all_agent_attempts_failed_is_not_a_usable_diagnosis():
    pipeline, orchestrator, _ = make_pipeline()
    use_real_attempts(orchestrator)
    for agent_type, agents in orchestrator._pool.items():
        for agent in agents:
            async def fail(req, selected=agent_type):
                return AgentResponse(selected, "failed", False)
            agent.handle = fail
    outcome = run_traced(pipeline, orchestrator).outcome
    assert outcome.result.agent_executions
    assert all(not attempt.success for attempt in outcome.result.agent_executions)
    assert outcome.trace.overall_status == "failed"


def test_assembler_parse_failure_keeps_markdown_and_degrades_trace():
    pipeline, orchestrator, _ = make_pipeline(fake_model("not json"))
    outcome = run_traced(pipeline, orchestrator).outcome
    assert outcome.diagnosis_build_result.diagnosis is None
    assert outcome.diagnosis_build_result.status.value == "parse_failed"
    assert outcome.result.response
    step = steps(outcome.trace, "diagnosis_assembly")[0]
    assert step.status == "failed" and step.error_code == "invalid_json"
    assert outcome.trace.overall_status == "degraded"


def test_clarification_skips_downstream_but_builds_deterministic_structure():
    pipeline, orchestrator, client = make_pipeline()
    unclear = intent(IntentCategory.OTHER, {})
    unclear.confidence = 0.1
    outcome = run_traced(pipeline, orchestrator, recognized=unclear,
                         message="不知道哪里出了问题").outcome
    assert outcome.clarification_required
    assert outcome.trace.overall_status == "success"
    assert all(steps(outcome.trace, name)[0].status == "skipped" for name in (
        "query_logs", "query_metrics", "query_deployments",
        "rag_rewrite", "rag_retrieval", "rag_rerank", "routing", "agent_execution",
    ))
    assembly = steps(outcome.trace, "diagnosis_assembly")[0]
    assert assembly.status == "success" and assembly.metadata["llm_called"] is False
    client.messages.create.assert_not_awaited()


def test_trace_disabled_assembler_and_recorder_failure_do_not_change_result(monkeypatch):
    pipeline, orchestrator, client = make_pipeline()
    outcome = run_traced(pipeline, orchestrator, build_diagnosis=False).outcome
    assert steps(outcome.trace, "diagnosis_assembly")[0].status == "skipped"
    client.messages.create.assert_not_awaited()

    def broken_begin(self, *args, **kwargs):
        raise RuntimeError("trace is unavailable")
    monkeypatch.setattr(TraceRecorder, "begin", broken_begin)
    again = run_traced(pipeline, orchestrator).outcome
    assert again.result.response == outcome.result.response
    assert again.diagnosis_build_result.diagnosis is not None


def test_recorder_whitelists_metadata_and_never_serializes_agent_text():
    recorder = TraceRecorder()
    token = activate_trace(recorder)
    try:
        step = begin_step("agent_execution", "AgentOrchestrator")
        finish_step(step, "success", metadata={
            "requested_agent": "application", "prompt": "SECRET-PROMPT",
            "authorization": "SECRET-AUTH", "content": "SECRET-MARKDOWN",
        })
        serialized = recorder.complete(request_id="abc", usable=True).model_dump_json()
    finally:
        reset_trace(token)
    assert "application" in serialized
    assert "SECRET-" not in serialized


def test_evaluation_run_id_is_optional_and_distinct_from_request_id():
    pipeline, orchestrator, _ = make_pipeline()
    orchestrator.recognize_intent = AsyncMock(return_value=intent())
    result = asyncio.run(run_diagnosis(
        orchestrator=orchestrator, pipeline=pipeline, message=MESSAGE,
        user_id="eval", conv_id="eval", eval_run_id="evaluation-run-1",
    ))
    trace = result.outcome.trace
    assert trace.eval_run_id == "evaluation-run-1"
    assert trace.request_id == result.outcome.result.request_id
    assert trace.trace_id not in {trace.eval_run_id, trace.request_id}


def test_real_rag_stages_are_timed_and_failure_fallback_is_observed():
    manager = MCPToolManager(api_key="offline", base_url="https://example.invalid")
    async def search(params, context):
        return [{"chunk_id": "c1", "content": "one"},
                {"chunk_id": "c2", "content": "two"}]
    manager.register(Tool("knowledge_search", "offline", search,
                          {"type": "object"}, supports_rerank=True))
    def response(value):
        return SimpleNamespace(stop_reason="end_turn", content=[{"type": "text", "text": value}])
    manager._client.messages.create = AsyncMock(side_effect=[
        response('["alternative"]'), response("[1, 0]"),
    ])
    recorder = TraceRecorder()
    token = activate_trace(recorder)
    try:
        result = asyncio.run(manager.search_with_rewrite("knowledge_search", "query", top_k=1))
        trace = recorder.complete(request_id=None, usable=True)
    finally:
        reset_trace(token)
    assert result.success and result.reranked
    assert [steps(trace, name)[0].status for name in (
        "rag_rewrite", "rag_retrieval", "rag_rerank")] == ["success"] * 3
    assert steps(trace, "rag_rerank")[0].knowledge_ids == ["c2"]
    assert steps(trace, "rag_retrieval")[0].knowledge_ids == ["c1", "c2"]


def test_rewrite_failure_uses_original_query_and_marks_degradation():
    manager = MCPToolManager(api_key="offline", base_url="https://example.invalid")
    observed_queries = []
    async def search(params, context):
        observed_queries.append(params["query"])
        return [{"chunk_id": "c1", "content": "answer"}]
    manager.register(Tool("knowledge_search", "offline", search, {"type": "object"}))
    manager._client.messages.create = AsyncMock(side_effect=RuntimeError("provider down"))
    recorder = TraceRecorder()
    token = activate_trace(recorder)
    try:
        result = asyncio.run(manager.search_with_rewrite("knowledge_search", "original"))
        trace = recorder.complete(request_id=None, usable=True)
    finally:
        reset_trace(token)
    assert observed_queries == ["original"] and result.success
    assert steps(trace, "rag_rewrite")[0].status == "degraded"
    assert steps(trace, "rag_retrieval")[0].status == "success"
    assert trace.overall_status == "degraded"
