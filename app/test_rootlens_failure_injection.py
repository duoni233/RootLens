"""Stage 5-2 controlled failures against the shared offline diagnosis path."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.agent_orchestrator import AgentResponse, AgentType
from api import main
from core.intent_recognizer import IntentCategory
from evaluation.rootlens_reliability import (
    ReliabilityExpectation, ReliabilityReport, observe_reliability, score_reliability,
)
from mcp.tool_manager import Tool
from test_rootlens_stage4_assembler import MESSAGE, intent, make_pipeline
from test_rootlens_stage5_trace import run_traced, steps, use_real_attempts
from test_support.failure_controller import FailurePlan, TestFailureController


def runtime(monkeypatch):
    pipeline, orchestrator, assembler_client = make_pipeline()
    use_real_attempts(orchestrator)
    manager = pipeline.tools

    async def knowledge_handler(params, context):
        return [{
            "document_id": "RL-RB-DB-001", "chunk_id": "RL-RB-DB-001:c0000",
            "source_ref": "knowledge/rootlens/db-connection-pool.md",
            "title": "Connection pool Runbook", "content": "Check pool utilization.",
            "metadata": {"source_type": "runbook"},
        }]

    manager.register(Tool(
        name="knowledge_search", description="offline runbook",
        handler=knowledge_handler, schema={"type": "object"}, cache_ttl=0,
        supports_rerank=True,
    ))
    manager._client.messages.create = AsyncMock(return_value=SimpleNamespace(
        stop_reason="end_turn", content=[{"type": "text", "text": '["pool runbook"]'}],
    ))
    monkeypatch.setattr(main, "_tool_manager", manager)
    pipeline.knowledge_lookup = main._retrieve_knowledge_context

    async def fallback(request):
        return AgentResponse(AgentType.GENERAL, "general fallback diagnosis", True)

    orchestrator._pool[AgentType.GENERAL][0].handle = fallback
    return pipeline, orchestrator, assembler_client


SCENARIOS = [
    ("logs-timeout", FailurePlan("query_logs", "timeout"), ReliabilityExpectation(
        "degraded", True, "success", failure_step="query_logs",
        expected_error_code="tool_timeout", diagnosis_degraded=True,
        unaffected_steps=("query_metrics", "query_deployments", "rag_retrieval"),
        response_contains="safe diagnosis")),
    ("metrics-exception", FailurePlan("query_metrics", "exception"), ReliabilityExpectation(
        "degraded", True, "success", failure_step="query_metrics",
        expected_error_code="tool_unavailable", diagnosis_degraded=True,
        unaffected_steps=("query_logs", "query_deployments", "rag_retrieval"),
        response_contains="safe diagnosis")),
    ("logs-empty", FailurePlan("query_logs", "empty"), ReliabilityExpectation(
        "success", False, "success", diagnosis_degraded=False,
        unaffected_steps=("query_metrics", "query_deployments", "rag_retrieval"),
        response_contains="safe diagnosis")),
    ("rewrite-exception", FailurePlan("rag_rewrite", "exception"), ReliabilityExpectation(
        "degraded", True, "success", failure_step="rag_rewrite",
        expected_error_code="rewrite_failed", diagnosis_degraded=True,
        unaffected_steps=("rag_retrieval", "query_logs", "query_metrics"),
        response_contains="safe diagnosis")),
    ("retrieval-exception", FailurePlan("rag_retrieval", "exception"), ReliabilityExpectation(
        "degraded", True, "success", failure_step="rag_retrieval",
        expected_error_code="retrieval_failed", diagnosis_degraded=True,
        unaffected_steps=("query_logs", "query_metrics", "query_deployments"),
        response_contains="safe diagnosis")),
    ("supporting-exception", FailurePlan("supporting_agent:database", "exception"),
     ReliabilityExpectation(
         "degraded", True, "success", failure_step="agent_execution",
         failure_role="supporting", expected_error_code="agent_exception",
         diagnosis_degraded=True,
         unaffected_steps=("query_logs", "rag_retrieval", "routing"),
         response_contains="application")),
    ("primary-fallback", FailurePlan("primary_agent:application", "failed_response"),
     ReliabilityExpectation(
         "degraded", True, "success", failure_step="agent_execution",
         failure_role="primary", expected_error_code="agent_failed",
         fallback=True, diagnosis_degraded=True,
         unaffected_steps=("query_logs", "rag_retrieval", "routing"),
         response_contains="general fallback diagnosis")),
    ("assembler-json", FailurePlan("diagnosis_assembler", "malformed_json"),
     ReliabilityExpectation(
         "degraded", True, "parse_failed", failure_step="diagnosis_assembly",
         expected_error_code="invalid_json", unaffected_steps=("query_logs", "routing"),
         response_contains="safe diagnosis")),
    ("assembler-api", FailurePlan("diagnosis_assembler", "api_exception"),
     ReliabilityExpectation(
         "degraded", True, "assembler_failed", failure_step="diagnosis_assembly",
         expected_error_code="model_api_error", unaffected_steps=("query_logs", "routing"),
         response_contains="safe diagnosis")),
    ("validation-unknown-id", FailurePlan("diagnosis_assembler", "invalid_ref"),
     ReliabilityExpectation(
         "degraded", True, "validation_failed", failure_step="diagnosis_assembly",
         expected_error_code="run_scope_validation_failed",
         unaffected_steps=("query_logs", "routing"),
         response_contains="safe diagnosis")),
]


@pytest.mark.parametrize("scenario_id,plan,expected", SCENARIOS,
                         ids=[row[0] for row in SCENARIOS])
def test_controlled_failure_is_observed_and_contained(monkeypatch, scenario_id, plan, expected):
    pipeline, orchestrator, _ = runtime(monkeypatch)
    with TestFailureController(pipeline, plan):
        outcome = run_traced(pipeline, orchestrator).outcome
    observed = observe_reliability(
        scenario_id=scenario_id, outcome=outcome, expected=expected,
        injected_target=plan.target, injected_failure=plan.failure,
    )
    assert observed.passed, {"scenario": scenario_id, "assertions": observed.assertions}
    if scenario_id == "logs-empty":
        assert steps(outcome.trace, "query_logs")[0].result_kind == "empty"
        assert outcome.bundle.tool_status["query_logs"].status == "empty"
    if scenario_id in {"logs-timeout", "metrics-exception"}:
        source = "log" if scenario_id == "logs-timeout" else "metric"
        assert all(item.source_type != source for item in outcome.bundle.evidence)
    if scenario_id == "retrieval-exception":
        assert outcome.knowledge.sources == []
        assert outcome.diagnosis_build_result.diagnosis.knowledge_refs == []
    if scenario_id == "supporting-exception":
        assert any(record.role == "supporting" and not record.success
                   for record in outcome.result.agent_executions)
        assert any("辅助 Agent" in gap.description for gap in
                   outcome.diagnosis_build_result.diagnosis.evidence_gaps)
    if scenario_id == "primary-fallback":
        attempts = [record for record in outcome.result.agent_executions
                    if record.requested_agent == AgentType.APPLICATION]
        assert [(item.executed_agent.value, item.success) for item in attempts] == [
            ("application", False), ("general_ops", True)]
    if scenario_id.startswith("assembler-") or scenario_id == "validation-unknown-id":
        assert outcome.diagnosis_build_result.diagnosis is None


def test_clarification_is_successful_early_stop(monkeypatch):
    pipeline, orchestrator, assembler_client = runtime(monkeypatch)
    missing_service = intent(IntentCategory.SERVICE_INCIDENT, {
        "start_time": ["10:05"], "status_code": ["5xx"],
    })
    outcome = run_traced(pipeline, orchestrator, recognized=missing_service,
                         message="10:05 开始 5xx 激增").outcome
    expected = ReliabilityExpectation(
        "success", False, "success", diagnosis_degraded=False,
        skipped_steps=("query_logs", "query_metrics", "query_deployments",
                       "rag_rewrite", "rag_retrieval", "rag_rerank",
                       "routing", "agent_execution"),
    )
    observed = observe_reliability(scenario_id="clarification", outcome=outcome,
                                   expected=expected)
    assert observed.passed, observed.assertions
    assert outcome.clarification_required
    assert steps(outcome.trace, "diagnosis_assembly")[0].metadata["llm_called"] is False
    assembler_client.messages.create.assert_not_awaited()


def test_without_controller_all_components_remain_normal(monkeypatch):
    pipeline, orchestrator, _ = runtime(monkeypatch)
    outcome = run_traced(pipeline, orchestrator).outcome
    expected = ReliabilityExpectation(
        "success", False, "success", diagnosis_degraded=False,
        unaffected_steps=("query_logs", "query_metrics", "query_deployments",
                          "rag_rewrite", "rag_retrieval", "routing",
                          "diagnosis_assembly"), response_contains="safe diagnosis",
    )
    observed = observe_reliability(scenario_id="normal", outcome=outcome,
                                   expected=expected)
    assert observed.passed, observed.assertions
    assert outcome.knowledge.sources[0].document_id == "RL-RB-DB-001"


def test_controller_restores_originals_and_rejects_bad_plan(monkeypatch):
    pipeline, orchestrator, _ = runtime(monkeypatch)
    with pytest.raises(ValueError, match="unsupported test failure"):
        FailurePlan("other_tool", "timeout")
    with pytest.raises(ValueError, match="unsupported test failure"):
        FailurePlan("query_logs", "malformed_json")
    tool = pipeline.tools._tools["query_logs"]
    original_handler, original_timeout = tool.handler, tool.timeout_s
    with TestFailureController(pipeline, FailurePlan("query_logs", "timeout")):
        assert tool.handler is not original_handler
        assert tool.timeout_s < original_timeout
    assert tool.handler is original_handler and tool.timeout_s == original_timeout
    assert run_traced(pipeline, orchestrator).outcome.trace.overall_status == "success"


def test_stage_five_report_is_separate_from_stage_three_baseline(monkeypatch):
    results = []
    for scenario_id, plan, expected in SCENARIOS:
        with monkeypatch.context() as patch:
            pipeline, orchestrator, _ = runtime(patch)
            with TestFailureController(pipeline, plan):
                outcome = run_traced(pipeline, orchestrator).outcome
            results.append(observe_reliability(
                scenario_id=scenario_id, outcome=outcome, expected=expected,
                injected_target=plan.target, injected_failure=plan.failure,
            ))
    with monkeypatch.context() as patch:
        pipeline, orchestrator, _ = runtime(patch)
        normal = run_traced(pipeline, orchestrator).outcome
        results.append(observe_reliability(
            scenario_id="normal", outcome=normal,
            expected=ReliabilityExpectation(
                "success", False, "success", diagnosis_degraded=False,
                unaffected_steps=("query_logs", "query_metrics", "query_deployments",
                                  "rag_retrieval", "routing", "diagnosis_assembly"),
                response_contains="safe diagnosis",
            ),
        ))
    with monkeypatch.context() as patch:
        pipeline, orchestrator, _ = runtime(patch)
        unclear = intent(IntentCategory.SERVICE_INCIDENT, {
            "start_time": ["10:05"], "status_code": ["5xx"],
        })
        clarification = run_traced(pipeline, orchestrator, recognized=unclear,
                                   message="10:05 开始 5xx 激增").outcome
        results.append(observe_reliability(
            scenario_id="clarification", outcome=clarification,
            expected=ReliabilityExpectation(
                "success", False, "success", diagnosis_degraded=False,
                skipped_steps=("query_logs", "query_metrics", "query_deployments",
                               "rag_rewrite", "rag_retrieval", "rag_rerank",
                               "routing", "agent_execution"),
            ),
        ))
    report = ReliabilityReport(results, score_reliability(results)).to_dict()
    assert all(item["assertions"]["containment"] for item in report["scenarios"])
    assert report["suite_name"] == "rootlens-stage5-reliability"
    assert set(report["metrics"]) == {
        "failure_detection_accuracy", "degraded_flag_accuracy",
        "fallback_observed_accuracy", "failure_containment_success_rate",
        "skipped_step_accuracy", "invalid_source_after_failure_count",
    }
    assert report["metrics"]["failure_detection_accuracy"] == {
        "numerator": 9, "denominator": 9, "value": 1.0}
    assert report["metrics"]["degraded_flag_accuracy"] == {
        "numerator": 12, "denominator": 12, "value": 1.0}
    assert report["metrics"]["fallback_observed_accuracy"] == {
        "numerator": 1, "denominator": 1, "value": 1.0}
    assert report["metrics"]["failure_containment_success_rate"] == {
        "numerator": 12, "denominator": 12, "value": 1.0}
    assert report["metrics"]["skipped_step_accuracy"] == {
        "numerator": 8, "denominator": 8, "value": 1.0}
    assert report["metrics"]["invalid_source_after_failure_count"] == {
        "numerator": 0, "denominator": 9, "value": 0}
