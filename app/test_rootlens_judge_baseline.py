"""Stage 3-3 Judge and baseline checks with no paid model calls."""
import asyncio
import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evaluation.rootlens_baseline import (
    BaselineStore, EVALUATION_SCHEMA_VERSION, JUDGE_SCHEMA_VERSION,
    SUITE_NAME, SUITE_VERSION,
)
from evaluation.rootlens_judge import JudgeResult, RootLensJudge, summarize_judgments


VALID = {
    "evidence_grounding": 0.8,
    "diagnostic_reasoning": 0.6,
    "actionability": 0.9,
    "safety_and_uncertainty": 0.7,
    "brief_reason": "Diagnosis is grounded and cautious.",
}


def judge_with_response(raw, *, stop_reason="end_turn", exception=None,
                        mode="diagnosis"):
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=raw)],
        stop_reason=stop_reason,
    )
    create = AsyncMock(side_effect=exception) if exception else AsyncMock(return_value=response)
    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    judge = RootLensJudge(client, "offline-model")
    result = asyncio.run(judge.judge(
        question="service 5xx", response="可能是连接池，请验证",
        operational_evidence=[{
            "evidence_id": "E-LOG-001", "source_type": "log",
            "summary": "DBConnectionError",
        }],
        knowledge_document_ids=["RL-RB-DB-001"],
        diagnosis_points=["connection pool"],
        forbidden_claims=["deployment caused the outage"],
        evaluation_mode=mode,
    ))
    return result, create


def test_valid_judge_json_and_prompt_inputs():
    result, create = judge_with_response(json.dumps(VALID))
    assert result.valid and result.raw_status == "valid"
    assert result.overall_score == pytest.approx(0.75)
    assert result.rationale == VALID["brief_reason"]
    prompt = create.call_args.kwargs["messages"][0]["content"]
    for value in ("E-LOG-001", "RL-RB-DB-001", "connection pool",
                  "deployment caused the outage"):
        assert value in prompt


@pytest.mark.parametrize("mode,required", [
    ("clarification", ("最小必要信息", "不要因为没有猜根因", "未指出具体缺项")),
    ("runbook", ("只查询 Runbook", "没有现场 Evidence 是正常的")),
    ("diagnosis", ("本例是故障诊断", "现场证据")),
])
def test_judge_mode_guidance_is_explicit(mode, required):
    result, create = judge_with_response(json.dumps(VALID), mode=mode)
    assert result.valid
    prompt = create.call_args.kwargs["messages"][0]["content"]
    assert f'"evaluation_mode": "{mode}"' in prompt
    for phrase in required:
        assert phrase in prompt


@pytest.mark.parametrize("raw,status", [
    ("not json", "invalid_json"),
    (json.dumps({key: value for key, value in VALID.items()
                 if key != "actionability"}), "invalid_schema"),
    (json.dumps({**VALID, "evidence_grounding": 1.2}), "invalid_schema"),
    (json.dumps({**VALID, "evidence_grounding": "0.8"}), "invalid_schema"),
    (json.dumps({**VALID, "evidence_grounding": True}), "invalid_schema"),
    (json.dumps({**VALID, "evidence_grounding": float("nan")}), "invalid_json"),
    (json.dumps({**VALID, "evidence_grounding": float("inf")}), "invalid_json"),
    (json.dumps({**VALID, "extra": 123}), "invalid_schema"),
])
def test_invalid_judge_outputs_are_not_scores(raw, status):
    result, _ = judge_with_response(raw)
    assert not result.valid and result.raw_status == status
    assert result.overall_score is None and result.evidence_grounding is None
    assert result.error


def test_truncated_and_api_error_are_invalid():
    truncated, _ = judge_with_response(json.dumps(VALID), stop_reason="max_tokens")
    failed, _ = judge_with_response("", exception=RuntimeError("offline failure"))
    assert (truncated.valid, truncated.raw_status) == (False, "truncated")
    assert (failed.valid, failed.raw_status) == (False, "api_error")


def test_judge_aggregation_uses_only_valid_cases():
    good = JudgeResult(valid=True, raw_status="valid", evidence_grounding=0.8,
                       diagnostic_reasoning=0.6, actionability=0.9,
                       safety_and_uncertainty=0.7, overall_score=0.75,
                       rationale="Grounded and cautious")
    bad = JudgeResult.invalid("invalid_json", "JSONDecodeError")
    summary = summarize_judgments([("a", good), ("b", bad)], ran=True)
    assert summary["status"] == "partial"
    assert (summary["valid_cases"], summary["failed_cases"],
            summary["coverage"]) == (1, 1, 0.5)
    assert summary["overall_mean"] == 0.75
    assert summary["per_dimension_mean"]["evidence_grounding"] == 0.8
    empty = summarize_judgments([("b", bad)], ran=True)
    assert empty["status"] == "failed" and empty["overall_mean"] is None
    assert empty["coverage"] == 0


def sample_report(*, judged=False):
    metrics = {
        name: {"numerator": 2, "denominator": 2, "value": 1.0}
        for name in (
            "intent_accuracy", "primary_agent_accuracy",
            "supporting_agent_exact_match", "evidence_required_coverage",
            "clarification_accuracy", "runbook_hit_accuracy",
        )
    }
    means = {
        "evidence_grounding": 0.8, "diagnostic_reasoning": 0.7,
        "actionability": 0.9, "safety_and_uncertainty": 0.8,
    } if judged else {}
    return {
        "suite": {
            "suite_name": SUITE_NAME, "suite_version": SUITE_VERSION,
            "dataset_id": "rootlens-demo", "dataset_version": "v1",
            "model": "offline-model", "provider": "offline-provider",
            "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
            "judge_schema_version": JUDGE_SCHEMA_VERSION,
            "case_ids": ["a", "b"], "suite_fingerprint": "sha256-sample",
        },
        "metrics": metrics,
        "judge": {
            "status": "complete" if judged else "not_run",
            "valid_cases": 2 if judged else 0,
            "failed_cases": 0, "coverage": 1.0 if judged else None,
            "per_dimension_mean": means,
            "overall_mean": 0.8 if judged else None,
        },
    }


def test_no_baseline_and_read_does_not_create_files(tmp_path):
    path = tmp_path / "rootlens" / "approved.json"
    store = BaselineStore(path)
    baseline, regression = store.compare(sample_report())
    assert baseline["baseline_id"] is None
    assert regression["status"] == "no_baseline"
    assert not path.exists()


def test_explicit_promote_preserves_history_and_complete_metadata(tmp_path):
    path = tmp_path / "rootlens" / "approved.json"
    store = BaselineStore(path)
    report = sample_report(judged=True)
    first = store.promote(report)
    second = store.promote(report)
    assert first.baseline_id != second.baseline_id
    assert store.load_approved().baseline_id == second.baseline_id
    assert (path.parent / "history" / f"{first.baseline_id}.json").exists()
    assert (path.parent / "history" / f"{second.baseline_id}.json").exists()
    metadata = second.metadata()
    for field in (
        "baseline_id", "suite_name", "suite_version", "dataset_version",
        "model", "provider", "evaluation_schema_version",
        "judge_schema_version", "created_at", "case_ids",
        "judge_valid_cases", "judge_failed_cases",
    ):
        assert field in metadata


@pytest.mark.parametrize("field", [
    "suite_name", "suite_version", "dataset_id", "dataset_version",
    "evaluation_schema_version", "judge_schema_version",
    "case_ids", "suite_fingerprint",
])
def test_incompatible_suite_or_data_cannot_be_compared(tmp_path, field):
    store = BaselineStore(tmp_path / "approved.json")
    store.promote(sample_report())
    current = copy.deepcopy(sample_report())
    current["suite"][field] = "changed"
    baseline, regression = store.compare(current)
    assert not baseline["compatible"]
    assert regression["status"] == "incompatible"
    assert regression["incompatibility_reason"] == [field]
    assert regression["metric_deltas"] == {}


def test_judge_mode_mismatch_is_incompatible(tmp_path):
    store = BaselineStore(tmp_path / "approved.json")
    store.promote(sample_report())
    _, regression = store.compare(sample_report(judged=True))
    assert regression["status"] == "incompatible"
    assert "judge_enabled" in regression["incompatibility_reason"]


def test_stage3_v1_judge_baseline_cannot_compare_to_v2(tmp_path):
    store = BaselineStore(tmp_path / "approved.json")
    previous = sample_report(judged=True)
    previous["suite"]["suite_version"] = "stage3-v1"
    previous["suite"]["judge_schema_version"] = "1"
    store.promote(previous)
    baseline, regression = store.compare(sample_report(judged=True))
    assert not baseline["compatible"]
    assert regression["status"] == "incompatible"
    assert set(regression["incompatibility_reason"]) == {
        "suite_version", "judge_schema_version",
    }
    assert regression["metric_deltas"] == {}
    assert regression["judge_deltas"] == {}


def test_regression_deltas_and_model_change_are_explicit(tmp_path):
    store = BaselineStore(tmp_path / "approved.json")
    store.promote(sample_report(judged=True))
    current = copy.deepcopy(sample_report(judged=True))
    current["suite"]["model"] = "new-model"
    current["metrics"]["intent_accuracy"]["value"] = 0.9
    current["judge"]["per_dimension_mean"]["evidence_grounding"] = 0.7
    current["judge"]["coverage"] = 0.5
    baseline, regression = store.compare(current)
    assert baseline["compatible"]
    assert regression["status"] == "compared_model_changed"
    assert regression["model_changed"]
    assert regression["metric_deltas"]["intent_accuracy"]["delta"] == pytest.approx(-0.1)
    assert regression["metric_deltas"]["intent_accuracy"]["status"] == "regressed"
    assert regression["judge_deltas"]["evidence_grounding"]["status"] == "regressed"
    assert regression["judge_deltas"]["coverage"]["status"] == "regressed"


def test_corrupt_approved_baseline_cannot_be_silently_replaced(tmp_path):
    path = tmp_path / "approved.json"
    path.write_text("bad JSON", encoding="utf-8")
    _, regression = BaselineStore(path).compare(sample_report())
    assert regression["status"] == "invalid_baseline"
    assert path.read_text(encoding="utf-8") == "bad JSON"


def test_cli_promotion_does_not_touch_legacy_baseline(tmp_path):
    report_path = tmp_path / "reviewed-report.json"
    approved_path = tmp_path / "rootlens" / "approved.json"
    legacy_path = tmp_path / "baseline.json"
    report_path.write_text(json.dumps(sample_report()), encoding="utf-8")
    legacy_path.write_text("legacy-baseline-sentinel", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "evaluation.rootlens_baseline", "promote",
         "--report", str(report_path), "--approved-path", str(approved_path)],
        cwd=Path(__file__).parent, capture_output=True, text=True, check=True,
    )
    output = json.loads(result.stdout)
    assert output["approved_path"] == str(approved_path)
    assert output["baseline_id"] == BaselineStore(approved_path).load_approved().baseline_id
    assert Path(output["snapshot_path"]).exists()
    assert legacy_path.read_text(encoding="utf-8") == "legacy-baseline-sentinel"
