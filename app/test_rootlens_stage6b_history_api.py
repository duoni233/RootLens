"""Stage 6B API integration without paid models or the runtime SQLite file."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import text

from core.incident_diagnosis import DiagnosisBuildStatus
from core.history_explanation import HistoryExplainer, archived_context
from evaluation.rootlens_baseline import BaselineStore
from evaluation.rootlens_cases import load_rootlens_cases
from evaluation.rootlens_evaluator import RootLensEvaluator
from mcp.tool_manager import ToolResult
from persistence.diagnosis_repository import DiagnosisRepository
from test_rootlens_stage4_api_evaluation import _api_runtime
from test_rootlens_stage4_assembler import fake_model, intent


TOKEN = "history-test-token-32-characters-long"
HEADERS = {"X-RootLens-History-Token": TOKEN}
MESSAGE = "payment-service 10:05 开始 5xx 激增"


def request(app, method, path, payload=None, headers=None):
    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                    base_url="http://test") as client:
            return await client.request(method, path, json=payload, headers=headers)
    return asyncio.run(call())


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    main, pipeline, orchestrator, client = _api_runtime(monkeypatch)
    repository = DiagnosisRepository(f"sqlite:///{tmp_path / 'history.sqlite3'}")
    repository.initialize()
    monkeypatch.setattr(main, "_history_repository", repository)
    monkeypatch.setattr(main, "_history_enabled", True)
    monkeypatch.setattr(main, "_history_api_enabled", True)
    monkeypatch.setattr(main, "_history_api_token", TOKEN)
    yield main, pipeline, orchestrator, repository, tmp_path
    repository.close()


def chat(main, message=MESSAGE):
    return request(main.app, "POST", "/chat", {"message": message})


def test_chat_saves_run_and_history_exposes_separate_shapes(runtime):
    main, _, _, repository, _ = runtime
    result = chat(main)
    assert result.status_code == 200
    body = result.json()
    assert body["persistence_status"] == "saved" and body["run_id"]
    run_id = body["run_id"]
    assert repository.get_run(run_id).response_markdown == body["response"]

    listing = request(main.app, "GET", "/diagnoses", headers=HEADERS)
    assert listing.status_code == 200
    summary = listing.json()["items"][0]
    assert summary["run_id"] == run_id
    assert "response_markdown" not in summary and "trace" not in summary
    assert "original_message" not in summary

    detail = request(main.app, "GET", f"/diagnoses/{run_id}", headers=HEADERS)
    assert detail.status_code == 200
    assert detail.json()["response_markdown"] == body["response"]
    assert detail.json()["diagnosis"] == body["diagnosis"]
    assert detail.json()["evidence_refs"]
    assert detail.json()["knowledge_refs"]
    assert "trace" not in detail.json()

    trace = request(main.app, "GET", f"/diagnoses/{run_id}/trace", headers=HEADERS)
    assert trace.status_code == 200
    assert trace.json()["trace_id"] == detail.json()["trace_id"]
    assert trace.json()["request_id"] == detail.json()["request_id"]
    assert trace.json()["steps"]


def test_history_explanation_uses_only_saved_diagnosis(runtime, monkeypatch):
    main, pipeline, orchestrator, repository, _ = runtime
    run_id = chat(main).json()["run_id"]
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(
        return_value=SimpleNamespace(content=[{"type": "text", "text": "事实有 E-1；发布根因未证实。"}]))))
    monkeypatch.setattr(main, "_history_explainer", HistoryExplainer(client, "offline"))
    pipeline.tools.call = AsyncMock(side_effect=AssertionError("tools must not run"))
    orchestrator.recognize_intent = AsyncMock(side_effect=AssertionError("intent must not run"))
    result = request(main.app, "POST", f"/diagnoses/{run_id}/explain",
                     {"question": "发布是否就是根因？"}, HEADERS)
    assert result.status_code == 200
    assert result.json()["basis"] == "saved_diagnosis"
    assert "未证实" in result.json()["answer"]
    assert len(repository.list_runs()) == 1
    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "confirmed_findings" in prompt and "hypotheses" in prompt
    assert "original_message" not in prompt and "trace" not in prompt
    assert "response_markdown" not in prompt
    assert "system" in client.messages.create.call_args.kwargs


def test_clarification_history_explains_limit_without_model(runtime, monkeypatch):
    main, _, orchestrator, repository, _ = runtime
    orchestrator.recognize_intent = AsyncMock(return_value=intent(
        entities={"start_time": ["10:05"]}))
    run_id = chat(main, "10:05 出现 5xx").json()["run_id"]
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    monkeypatch.setattr(main, "_history_explainer", HistoryExplainer(client, "offline"))
    result = request(main.app, "POST", f"/diagnoses/{run_id}/explain",
                     {"question": "有哪些证据？"}, HEADERS)
    assert result.status_code == 200
    assert result.json()["basis"] == "insufficient_record"
    assert "没有形成现场证据" in result.json()["answer"]
    client.messages.create.assert_not_called()
    assert len(repository.list_runs()) == 1


def test_explanation_auth_validation_and_failure_are_bounded(runtime, monkeypatch):
    main, _, _, repository, _ = runtime
    run_id = chat(main).json()["run_id"]
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(
        side_effect=RuntimeError("PRIVATE_PROVIDER_SECRET"))))
    monkeypatch.setattr(main, "_history_explainer", HistoryExplainer(client, "offline"))
    path = f"/diagnoses/{run_id}/explain"
    assert request(main.app, "POST", path, {"question": "分析"}).status_code == 401
    assert request(main.app, "POST", path, {"question": "  "}, HEADERS).status_code == 422
    assert request(main.app, "POST", path, {"question": "x" * 1001}, HEADERS).status_code == 422
    assert request(main.app, "POST", "/diagnoses/absent/explain",
                   {"question": "分析"}, HEADERS).status_code == 404
    failure = request(main.app, "POST", path, {"question": "分析"}, HEADERS)
    assert failure.status_code == 503
    assert "PRIVATE_PROVIDER_SECRET" not in failure.text
    assert len(repository.list_runs()) == 1


def test_archived_context_excludes_unvalidated_text(runtime):
    main, _, _, repository, _ = runtime
    run_id = chat(main).json()["run_id"]
    context = archived_context(repository.get_run(run_id))
    assert context["confirmed_findings"]
    assert "original_message" not in context
    assert "response_markdown" not in context


@pytest.mark.parametrize("credential", [
    "password=demo-secret-123", "API_KEY=demo-secret-123",
    "Authorization: Bearer demo-secret-123", "密码是demo-secret-123",
])
def test_credential_like_content_never_enters_history(runtime, credential):
    main, _, _, repository, _ = runtime
    body = chat(main, f"{MESSAGE} {credential}").json()
    assert body["response"]
    assert body["persistence_status"] == "failed"
    assert body["run_id"] is None
    assert repository.list_runs() == []


def test_clarification_and_failed_structure_are_saved(runtime):
    main, _, orchestrator, repository, _ = runtime
    orchestrator.recognize_intent = AsyncMock(return_value=intent(
        entities={"start_time": ["10:05"]}))
    clarification = chat(main, "10:05 出现 5xx")
    assert clarification.status_code == 200
    assert clarification.json()["persistence_status"] == "saved"
    saved = repository.get_run(clarification.json()["run_id"])
    assert saved.clarification_required and saved.primary_agent is None

    main._diagnosis_pipeline.assembler.client = fake_model("not json")
    orchestrator.recognize_intent = AsyncMock(return_value=intent())
    failed = chat(main)
    assert failed.status_code == 200
    assert failed.json()["diagnosis_status"] == "parse_failed"
    assert failed.json()["persistence_status"] == "saved"
    saved = repository.get_run(failed.json()["run_id"])
    assert saved.diagnosis is None and saved.response_markdown


def test_tool_failure_saves_degraded_trace(runtime):
    main, pipeline, _, repository, _ = runtime
    original = pipeline.tools.call

    async def fail_logs(name, params):
        if name == "query_logs":
            return ToolResult(False, None, name, error="offline failure")
        return await original(name, params)

    pipeline.tools.call = fail_logs
    body = chat(main).json()
    assert body["persistence_status"] == "saved"
    saved = repository.get_run(body["run_id"])
    assert saved.degraded and saved.trace_status == "degraded"
    assert any(step.step_type == "query_logs" and step.status == "failed"
               for step in saved.trace.steps)


def test_database_write_failure_keeps_chat_and_hides_error(runtime, monkeypatch):
    main, _, _, repository, _ = runtime

    def broken(_run):
        raise RuntimeError("PRIVATE_DB_PATH_OR_SECRET")

    monkeypatch.setattr(repository, "save_run", broken)
    result = chat(main)
    assert result.status_code == 200
    assert result.json()["diagnosis_status"] == "success"
    assert result.json()["response"]
    assert result.json()["run_id"] is None
    assert result.json()["persistence_status"] == "failed"
    assert "PRIVATE_DB_PATH_OR_SECRET" not in result.text
    assert repository.list_runs() == []


def test_history_disabled_and_token_boundary(runtime, monkeypatch):
    main, _, _, _, _ = runtime
    monkeypatch.setattr(main, "_history_api_enabled", False)
    assert request(main.app, "GET", "/diagnoses", headers=HEADERS).status_code == 404
    monkeypatch.setattr(main, "_history_api_enabled", True)
    assert request(main.app, "GET", "/diagnoses").status_code == 401
    assert request(main.app, "GET", "/diagnoses", headers={
        "X-RootLens-History-Token": "wrong"}).status_code == 401
    assert request(main.app, "GET", "/diagnoses", headers=HEADERS).status_code == 200
    monkeypatch.setattr(main, "_history_enabled", False)
    body = chat(main).json()
    assert body["persistence_status"] == "disabled" and body["run_id"] is None


def test_list_pagination_filters_and_invalid_inputs(runtime):
    main, _, orchestrator, _, _ = runtime
    first = chat(main).json()
    orchestrator.recognize_intent = AsyncMock(return_value=intent(
        entities={"start_time": ["10:05"]}))
    second = chat(main, "10:05 出现 5xx").json()
    assert first["run_id"] != second["run_id"]
    page = request(main.app, "GET", "/diagnoses?limit=1&offset=1", headers=HEADERS)
    assert page.status_code == 200 and len(page.json()["items"]) == 1
    match = request(main.app, "GET", "/diagnoses?service_name=payment-service",
                    headers=HEADERS)
    assert [item["run_id"] for item in match.json()["items"]] == [first["run_id"]]
    partial = request(main.app, "GET", "/diagnoses?service_name=PAY",
                      headers=HEADERS)
    assert [item["run_id"] for item in partial.json()["items"]] == [first["run_id"]]
    missing = request(main.app, "GET", "/diagnoses?service_missing=true",
                      headers=HEADERS)
    assert [item["run_id"] for item in missing.json()["items"]] == [second["run_id"]]
    clarification = request(main.app, "GET", "/diagnoses?clarification_required=true",
                            headers=HEADERS)
    assert [item["run_id"] for item in clarification.json()["items"]] == [second["run_id"]]
    filtered = request(main.app, "GET", "/diagnoses?diagnosis_status=success&degraded=false",
                       headers=HEADERS)
    assert len(filtered.json()["items"]) == 2
    assert request(main.app, "GET", "/diagnoses?limit=101", headers=HEADERS).status_code == 422
    assert request(main.app, "GET", "/diagnoses?offset=-1", headers=HEADERS).status_code == 422
    assert request(main.app, "GET", "/diagnoses?diagnosis_status=bad",
                   headers=HEADERS).status_code == 422


def test_unknown_run_and_future_schema_are_safe(runtime):
    main, _, _, repository, _ = runtime
    assert request(main.app, "GET", "/diagnoses/missing", headers=HEADERS).status_code == 404
    assert request(main.app, "GET", "/diagnoses/missing/trace",
                   headers=HEADERS).status_code == 404
    run_id = chat(main).json()["run_id"]
    with repository.engine.begin() as connection:
        connection.execute(text("UPDATE diagnosis_runs SET trace_json=:snapshot WHERE run_id=:id"),
                           {"snapshot": '{"schema_version":"2"}', "id": run_id})
    result = request(main.app, "GET", f"/diagnoses/{run_id}", headers=HEADERS)
    assert result.status_code == 409 and "Traceback" not in result.text


def test_evaluation_never_writes_user_history(runtime, monkeypatch):
    main, pipeline, orchestrator, repository, tmp_path = runtime
    evaluator = RootLensEvaluator(
        orchestrator=orchestrator, pipeline=pipeline,
        baseline_store=BaselineStore(tmp_path / "approved.json"),
        model="offline", provider="test",
    )
    monkeypatch.setattr(main, "_rootlens_evaluator", evaluator)
    case = load_rootlens_cases()[0].model_dump(mode="json")
    result = request(main.app, "POST", "/eval/run", {"cases": [case]})
    assert result.status_code == 200
    assert repository.list_runs() == []


def test_repository_reopen_keeps_history(runtime, monkeypatch):
    main, _, _, repository, tmp_path = runtime
    run_id = chat(main).json()["run_id"]
    repository.close()
    reopened = DiagnosisRepository(f"sqlite:///{tmp_path / 'history.sqlite3'}")
    try:
        reopened.initialize()
        monkeypatch.setattr(main, "_history_repository", reopened)
        result = request(main.app, "GET", f"/diagnoses/{run_id}", headers=HEADERS)
        assert result.status_code == 200
        assert result.json()["run_id"] == run_id
    finally:
        reopened.close()
