"""Stage 4-3 API and evaluation contracts, exercised without paid models."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from core.incident_diagnosis import DiagnosisBuildStatus
from core.diagnosis_pipeline import KnowledgeResult, KnowledgeSource
from evaluation.rootlens_baseline import BaselineStore
from evaluation.rootlens_cases import load_rootlens_cases
from evaluation.rootlens_evaluator import RootLensEvaluator
from evaluation.rootlens_structured import observe_structured, score_structured
from test_rootlens_stage4_assembler import fake_model, intent, make_pipeline, run_pipeline


def _request(app, method, path, payload=None):
    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                    base_url="http://test") as client:
            return await client.request(method, path, json=payload)
    return asyncio.run(call())


def _api_runtime(monkeypatch, model=None):
    from api import main

    pipeline, orchestrator, client = make_pipeline(model)
    orchestrator.recognize_intent = AsyncMock(return_value=intent())
    memory_context = SimpleNamespace(recent_messages=[], to_prompt_text=lambda: "")
    memory = SimpleNamespace(
        get_context=AsyncMock(return_value=memory_context),
        add_message=AsyncMock(), enable_user_profile=False,
    )
    monkeypatch.setattr(main, "_orchestrator", orchestrator)
    monkeypatch.setattr(main, "_diagnosis_pipeline", pipeline)
    monkeypatch.setattr(main, "_memory", memory)
    return main, pipeline, orchestrator, client


def test_chat_exposes_success_without_replacing_legacy_response(monkeypatch):
    main, _, _, _ = _api_runtime(monkeypatch)
    response = _request(main.app, "POST", "/chat", {"message": "payment-service 10:05 5xx"})
    assert response.status_code == 200
    body = response.json()
    assert body["diagnosis_status"] == "success"
    assert body["diagnosis"]["schema_version"] == "1"
    assert body["diagnosis"]["primary_agent"] == "application"
    assert body["response"] == ("[application - 主处理]\n原来的 Markdown 回复\n\n"
                                "[database - 辅助处理]\n原来的 Markdown 回复")
    assert "agent_executions" not in body
    assert isinstance(body["response"], str)


def test_chat_failure_leaves_original_reply_available(monkeypatch):
    main, _, _, _ = _api_runtime(monkeypatch, fake_model("not json"))
    response = _request(main.app, "POST", "/chat", {"message": "payment-service 10:05 5xx"})
    assert response.status_code == 200
    assert response.json()["diagnosis_status"] == "parse_failed"
    assert response.json()["diagnosis"] is None
    assert "原来的 Markdown 回复" in response.json()["response"]


def test_chat_clarification_exposes_valid_structure_without_model(monkeypatch):
    main, _, orchestrator, client = _api_runtime(monkeypatch)
    missing = intent(entities={"start_time": ["10:05"]})
    orchestrator.recognize_intent = AsyncMock(return_value=missing)
    response = _request(main.app, "POST", "/chat", {"message": "10:05 出现 5xx"})
    assert response.status_code == 200
    body = response.json()
    assert body["diagnosis_status"] == "success"
    assert body["diagnosis"]["status"] == "clarification"
    assert body["diagnosis"]["clarification_question"] == body["response"]
    assert not body["diagnosis"]["confirmed_findings"]
    client.messages.create.assert_not_awaited()


def test_structured_metrics_keep_not_applicable_denominators():
    pipeline, _, _ = make_pipeline()
    diagnostic = run_pipeline(pipeline)
    first = observe_structured("INC-001", intent(), diagnostic)
    clarifier = intent(entities={"start_time": ["10:05"]})
    second = observe_structured("clarify", clarifier,
                                run_pipeline(pipeline, recognized=clarifier))
    scores = score_structured([first, second])
    assert scores["diagnosis_build_success_rate"].numerator == 2
    assert scores["diagnosis_build_success_rate"].denominator == 2
    assert scores["structured_schema_valid_rate"].value == 1
    assert scores["invalid_evidence_ref_count"].value == 0
    assert scores["confirmed_finding_source_coverage"].denominator == 1
    assert scores["approval_policy_accuracy"].denominator == 0
    assert scores["approval_policy_accuracy"].value is None
    assert scores["clarification_structure_accuracy"].denominator == 1
    assert scores["clarification_structure_accuracy"].value == 1
    assert scores["degraded_flag_accuracy"].denominator == 2
    assert scores["degraded_flag_accuracy"].value == 1


def test_structured_failure_does_not_create_fake_validity_metrics():
    pipeline, _, _ = make_pipeline(fake_model("not json"))
    observed = observe_structured("bad", intent(), run_pipeline(pipeline))
    scores = score_structured([observed])
    assert observed.diagnosis_build_status == DiagnosisBuildStatus.PARSE_FAILED.value
    assert scores["diagnosis_build_success_rate"].value == 0
    assert scores["structured_schema_valid_rate"].denominator == 0
    assert scores["structured_schema_valid_rate"].value is None


def test_invalid_runtime_source_fails_structure_without_crashing_observation():
    pipeline, _, client = make_pipeline()

    async def invalid_knowledge(query):
        return KnowledgeResult(sources=[KnowledgeSource(
            document_id="", chunk_id="chunk", source_ref="source")])

    pipeline.knowledge_lookup = invalid_knowledge
    outcome = run_pipeline(pipeline)
    observed = observe_structured("invalid-runtime", intent(), outcome)
    assert observed.diagnosis_build_status == "validation_failed"
    assert observed.structured_diagnosis is None
    client.messages.create.assert_not_awaited()


def test_evaluation_opt_in_keeps_stage3_report_and_baseline_contract(
        monkeypatch, tmp_path):
    main, pipeline, orchestrator, client = _api_runtime(monkeypatch)
    evaluator = RootLensEvaluator(
        orchestrator=orchestrator, pipeline=pipeline,
        baseline_store=BaselineStore(tmp_path / "approved.json"),
        model="offline", provider="test",
    )
    monkeypatch.setattr(main, "_rootlens_evaluator", evaluator)
    case = load_rootlens_cases()[0].model_dump(mode="json")
    plain = _request(main.app, "POST", "/eval/run", {"cases": [case]})
    assert plain.status_code == 200
    assert "structured" not in plain.json()
    client.messages.create.assert_not_awaited()

    enriched = _request(main.app, "POST", "/eval/run",
                        {"cases": [case], "include_structured": True})
    assert enriched.status_code == 200
    output = enriched.json()
    assert output["suite"] == plain.json()["suite"]
    assert output["metrics"] == plain.json()["metrics"]
    assert output["observations"][0].keys() == plain.json()["observations"][0].keys()
    assert output["structured"]["metrics"]["diagnosis_build_success_rate"]["value"] == 1
    assert output["structured"]["observations"][0]["diagnosis_build_status"] == "success"
    assert client.messages.create.await_count == 1
    assert not (tmp_path / "approved.json").exists()


def test_legacy_eval_rejects_structured_option(monkeypatch):
    main, _, _, _ = _api_runtime(monkeypatch)
    response = _request(main.app, "POST", "/eval/run",
                        {"mode": "legacy", "include_structured": True})
    assert response.status_code == 400


def test_model_token_usage_is_observed_when_provider_returns_it():
    client = fake_model()
    original = client.messages.create

    async def with_usage(**kwargs):
        response = await original(**kwargs)
        response.usage = SimpleNamespace(input_tokens=120, output_tokens=80)
        return response

    client.messages.create = AsyncMock(side_effect=with_usage)
    pipeline, _, _ = make_pipeline(client)
    result = run_pipeline(pipeline).diagnosis_build_result
    assert result.status == DiagnosisBuildStatus.SUCCESS
    assert result.assembler_latency_ms is not None
    assert result.input_tokens == 120 and result.output_tokens == 80
