"""Stage 6A diagnosis history checks; no live model or runtime database."""
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from agents.agent_orchestrator import AgentExecutionRecord, AgentType
from core.diagnosis_entry import run_diagnosis
from core.incident_diagnosis import DiagnosisBuildStatus
from core.intent_recognizer import IntentCategory
from mcp.tool_manager import ToolResult
from persistence.diagnosis_persistence import build_diagnosis_run
from persistence.diagnosis_repository import (
    DiagnosisHistoryError, DiagnosisRepository, UnsupportedSchemaVersion,
)
from test_rootlens_stage4_assembler import (
    MESSAGE, fake_model, intent, make_pipeline, runbook_synthesis,
)


@pytest.fixture
def repository(tmp_path):
    repo = DiagnosisRepository(f"sqlite:///{tmp_path / 'history.sqlite3'}")
    repo.initialize()
    yield repo
    repo.close()


def observed(*, recognized=None, message=MESSAGE, model=None, eval_run_id=None,
             change_tools=None):
    pipeline, orchestrator, _ = make_pipeline(model)
    orchestrator.recognize_intent = AsyncMock(return_value=recognized or intent())
    if change_tools is not None:
        change_tools(pipeline)
    return asyncio.run(run_diagnosis(
        orchestrator=orchestrator, pipeline=pipeline,
        message=message, user_id="offline", conv_id="offline",
        eval_run_id=eval_run_id,
    ))


def record(*, recognized=None, message=MESSAGE, model=None, change_tools=None):
    diagnosis = observed(recognized=recognized, message=message, model=model,
                         change_tools=change_tools)
    return build_diagnosis_run(diagnosis=diagnosis, message=message,
                               conversation_id="conversation-1")


def test_normal_diagnosis_round_trips_every_snapshot(repository):
    run = record()
    assert run.diagnosis_status == DiagnosisBuildStatus.SUCCESS
    assert run.diagnosis is not None and run.trace is not None
    assert run.run_id != run.trace_id
    assert run.request_id == run.trace.request_id
    repository.save_run(run)
    loaded = repository.get_run(run.run_id)
    assert loaded == run
    assert loaded.diagnosis.schema_version == "1"
    assert loaded.trace.schema_version == "1"
    assert loaded.trace.steps == run.trace.steps
    assert loaded.evidence_refs and loaded.knowledge_refs
    assert loaded.response_markdown == run.response_markdown
    assert loaded.created_at.tzinfo is not None
    assert repository.get_run("missing") is None


def test_clarification_is_saved_without_agent_or_evidence(repository):
    run = record(recognized=intent(entities={"start_time": ["10:05"]}))
    assert run.clarification_required and run.primary_agent is None
    assert not run.evidence_refs
    repository.save_run(run)
    loaded = repository.get_run(run.run_id)
    assert loaded.clarification_required
    assert loaded.response_markdown
    assert loaded.trace is not None


def test_partial_tool_failure_is_degraded_and_preserved(repository):
    def fail_logs(pipeline):
        original = pipeline.tools.call

        async def call(name, params):
            if name == "query_logs":
                return ToolResult(False, None, name, error="offline failure")
            return await original(name, params)

        pipeline.tools.call = call

    run = record(change_tools=fail_logs)
    assert run.degraded and run.trace_status == "degraded"
    repository.save_run(run)
    loaded = repository.get_run(run.run_id)
    assert loaded.degraded
    assert any(step.step_type == "query_logs" and step.status == "failed"
               for step in loaded.trace.steps)


def test_agent_fallback_metadata_is_preserved(repository):
    diagnosis = observed()
    diagnosis.outcome.result.agent_executions[0].degraded = True
    diagnosis.outcome.result.agent_executions[0].executed_agent = AgentType.GENERAL
    run = build_diagnosis_run(diagnosis=diagnosis, message=MESSAGE)
    assert run.degraded
    repository.save_run(run)
    loaded = repository.get_run(run.run_id)
    assert loaded.degraded and loaded.response_markdown == run.response_markdown


@pytest.mark.parametrize("output,status", [
    ("not JSON", DiagnosisBuildStatus.PARSE_FAILED),
    ({"summary": "x", "unknown": "field"}, DiagnosisBuildStatus.VALIDATION_FAILED),
])
def test_structure_failure_keeps_markdown(repository, output, status):
    run = record(model=fake_model(output))
    assert run.diagnosis_status == status and run.diagnosis is None
    assert run.response_markdown
    repository.save_run(run)
    loaded = repository.get_run(run.run_id)
    assert loaded.diagnosis is None and loaded.response_markdown == run.response_markdown
    assert loaded.trace is not None


def test_assembler_api_failure_keeps_markdown(repository):
    run = record(model=fake_model(error=RuntimeError("offline provider error")))
    assert run.diagnosis_status == DiagnosisBuildStatus.ASSEMBLER_FAILED
    repository.save_run(run)
    assert repository.get_run(run.run_id).response_markdown == run.response_markdown


def test_without_trace_still_preserves_markdown(repository):
    diagnosis = observed()
    diagnosis.outcome.trace = None
    run = build_diagnosis_run(diagnosis=diagnosis, message=MESSAGE)
    assert run.trace is None and run.trace_id is None
    repository.save_run(run)
    assert repository.get_run(run.run_id).trace is None


def test_list_sorting_pagination_and_filters(repository):
    first = record()
    second = record(recognized=intent(IntentCategory.RUNBOOK_QUERY),
                    message="怎么处理 payment-service 连接池问题？",
                    model=fake_model(runbook_synthesis()))
    third = record(recognized=intent(entities={"start_time": ["10:05"]}))
    second.created_at = first.created_at + timedelta(seconds=1)
    second.completed_at = second.created_at + timedelta(seconds=1)
    third.created_at = first.created_at + timedelta(seconds=2)
    third.completed_at = third.created_at + timedelta(seconds=1)
    for run in (second, first, third):
        repository.save_run(run)
    assert [run.run_id for run in repository.list_runs()] == [
        third.run_id, second.run_id, first.run_id]
    assert [run.run_id for run in repository.list_runs(limit=1, offset=1)] == [second.run_id]
    assert [run.run_id for run in repository.list_runs(service_name="payment-service")] == [
        second.run_id, first.run_id]
    assert [run.run_id for run in repository.list_runs(service_name="PAY")] == [
        second.run_id, first.run_id]
    assert repository.list_runs(service_name="%") == []
    assert [run.run_id for run in repository.list_runs(service_missing=True)] == [third.run_id]
    assert [run.run_id for run in repository.list_runs(service_missing=False)] == [
        second.run_id, first.run_id]
    assert [run.run_id for run in repository.list_runs(clarification_required=True)] == [
        third.run_id]
    assert repository.list_runs(service_name="other-service") == []
    assert [run.run_id for run in repository.list_runs(
        diagnosis_status=DiagnosisBuildStatus.SUCCESS.value)] == [
        third.run_id, second.run_id, first.run_id]
    assert repository.list_runs(degraded=True) == []
    with pytest.raises(ValueError):
        repository.list_runs(limit=0)
    with pytest.raises(ValueError):
        repository.list_runs(offset=-1)


def test_duplicate_run_id_fails_explicitly(repository):
    run = record()
    repository.save_run(run)
    with pytest.raises(DiagnosisHistoryError, match="duplicate run_id"):
        repository.save_run(run)
    assert len(repository.list_runs()) == 1


@pytest.mark.parametrize("column", ["schema_version", "diagnosis_json", "trace_json"])
def test_unknown_schema_version_is_rejected(repository, column):
    run = record()
    repository.save_run(run)
    value = ("2" if column == "schema_version" else
             '{"schema_version":"2"}')
    with repository.engine.begin() as connection:
        connection.execute(
            text(f"UPDATE diagnosis_runs SET {column}=:value WHERE run_id=:run_id"),
            {"value": value, "run_id": run.run_id},
        )
    with pytest.raises(UnsupportedSchemaVersion):
        repository.get_run(run.run_id)


def test_evaluation_trace_cannot_enter_runtime_history(repository):
    diagnosis = observed(eval_run_id="eval-001")
    with pytest.raises(ValueError, match="evaluation"):
        build_diagnosis_run(diagnosis=diagnosis, message=MESSAGE)
    assert repository.list_runs() == []


def test_temporary_database_isolation(repository, tmp_path):
    repository.save_run(record())
    other = DiagnosisRepository(f"sqlite:///{tmp_path / 'other.sqlite3'}")
    try:
        other.initialize()
        assert other.list_runs() == []
    finally:
        other.close()


def test_initialize_creates_only_configured_sqlite_directory(tmp_path):
    path = tmp_path / "nested" / "history" / "diagnoses.sqlite3"
    repo = DiagnosisRepository(f"sqlite:///{path}")
    try:
        assert not path.parent.exists()
        repo.initialize()
        assert path.exists()
        assert repo.list_runs() == []
    finally:
        repo.close()


def test_no_agent_private_content_or_prompt_is_persisted(repository, tmp_path):
    diagnosis = observed()
    diagnosis.outcome.result.agent_executions.append(AgentExecutionRecord(
        requested_agent=AgentType.DATABASE, executed_agent=AgentType.DATABASE,
        role="supporting", success=True, content="PRIVATE_AGENT_CONTENT_ONLY"))
    diagnosis.outcome.hidden_prompt = "PRIVATE_SYSTEM_PROMPT_ONLY"
    run = build_diagnosis_run(diagnosis=diagnosis, message=MESSAGE)
    repository.save_run(run)
    raw = (tmp_path / "history.sqlite3").read_bytes()
    assert b"PRIVATE_AGENT_CONTENT_ONLY" not in raw
    assert b"PRIVATE_SYSTEM_PROMPT_ONLY" not in raw
    assert not hasattr(repository.get_run(run.run_id), "agent_executions")
