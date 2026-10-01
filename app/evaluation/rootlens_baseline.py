"""Versioned RootLens baselines; ordinary evaluation never writes an approved file."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from evaluation.rootlens_cases import EvaluationCase
from evaluation.rootlens_judge import DIMENSIONS


SUITE_NAME = "rootlens-diagnosis"
SUITE_VERSION = "stage3-v2"
EVALUATION_SCHEMA_VERSION = "1"
JUDGE_SCHEMA_VERSION = "2"
DEFAULT_APPROVED_PATH = Path("/app/data/eval/rootlens/approved.json")
REGRESSION_DROP = 0.05  # Absolute score-point drop on 0..1 metrics.
DETERMINISTIC_COMPARISONS = (
    "intent_accuracy", "primary_agent_accuracy",
    "supporting_agent_exact_match", "evidence_required_coverage",
    "clarification_accuracy", "runbook_hit_accuracy",
)


class MetricSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numerator: float = Field(allow_inf_nan=False)
    denominator: int = Field(ge=0)
    value: Optional[float] = Field(default=None, allow_inf_nan=False)


class BaselineRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_id: str
    approved: bool
    suite_name: str
    suite_version: str
    dataset_id: str
    dataset_version: str
    model: str
    provider: str
    evaluation_schema_version: str
    judge_schema_version: str
    created_at: AwareDatetime
    case_ids: list[str]
    suite_fingerprint: str
    deterministic_metrics: dict[str, MetricSnapshot]
    judge_enabled: bool
    judge_metrics: dict[str, Optional[float]]
    judge_valid_cases: int = Field(ge=0)
    judge_failed_cases: int = Field(ge=0)

    def metadata(self) -> dict[str, Any]:
        return self.model_dump(
            mode="json",
            exclude={
                "deterministic_metrics", "judge_metrics",
            },
        )


class BaselineError(ValueError):
    pass


def suite_fingerprint(cases: list[EvaluationCase]) -> str:
    payload = [case.model_dump(mode="json") for case in
               sorted(cases, key=lambda item: item.case_id)]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=".baseline-", suffix=".tmp", delete=False,
        ) as stream:
            name = stream.name
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def _record_from_report(report: dict) -> BaselineRecord:
    try:
        suite = report["suite"]
        judge = report["judge"]
        enabled = judge["status"] != "not_run"
        return BaselineRecord(
            baseline_id=uuid4().hex, approved=True,
            suite_name=suite["suite_name"], suite_version=suite["suite_version"],
            dataset_id=suite["dataset_id"], dataset_version=suite["dataset_version"],
            model=suite["model"], provider=suite["provider"],
            evaluation_schema_version=suite["evaluation_schema_version"],
            judge_schema_version=suite["judge_schema_version"],
            created_at=datetime.now(timezone.utc),
            case_ids=suite["case_ids"], suite_fingerprint=suite["suite_fingerprint"],
            deterministic_metrics=report["metrics"],
            judge_enabled=enabled,
            judge_metrics={
                **judge.get("per_dimension_mean", {}),
                "overall_mean": judge.get("overall_mean"),
                "coverage": judge.get("coverage"),
            },
            judge_valid_cases=judge["valid_cases"],
            judge_failed_cases=judge["failed_cases"],
        )
    except (KeyError, TypeError, ValidationError) as ex:
        raise BaselineError(f"invalid evaluation report: {type(ex).__name__}") from ex


class BaselineStore:
    def __init__(self, approved_path: Path = DEFAULT_APPROVED_PATH):
        self.path = Path(approved_path)

    def load_approved(self) -> Optional[BaselineRecord]:
        if not self.path.exists():
            return None
        try:
            record = BaselineRecord.model_validate_json(self.path.read_text(encoding="utf-8"))
            if not record.approved:
                raise BaselineError("baseline is not approved")
            return record
        except (OSError, ValidationError, ValueError) as ex:
            raise BaselineError(f"invalid approved baseline: {type(ex).__name__}") from ex

    def promote(self, report: dict) -> BaselineRecord:
        """Explicit local operation; preserve each approved snapshot by ID."""
        record = _record_from_report(report)
        payload = record.model_dump(mode="json")
        snapshot = self.path.parent / "history" / f"{record.baseline_id}.json"
        _atomic_json(snapshot, payload)
        _atomic_json(self.path, payload)
        return record

    def compare(self, report: dict) -> tuple[dict, dict]:
        try:
            previous = self.load_approved()
        except BaselineError as ex:
            return (
                {"baseline_id": None, "compatible": False, "metadata": None},
                {"status": "invalid_baseline", "metric_deltas": {},
                 "judge_deltas": {}, "incompatibility_reason": [str(ex)],
                 "model_changed": False},
            )
        if previous is None:
            return (
                {"baseline_id": None, "compatible": False, "metadata": None},
                {"status": "no_baseline", "metric_deltas": {},
                 "judge_deltas": {}, "incompatibility_reason": [],
                 "model_changed": False},
            )

        suite = report["suite"]
        required = (
            "suite_name", "suite_version", "dataset_id", "dataset_version",
            "evaluation_schema_version", "judge_schema_version",
            "case_ids", "suite_fingerprint",
        )
        reasons = [field for field in required
                   if getattr(previous, field) != suite[field]]
        judge_enabled = report["judge"]["status"] != "not_run"
        if previous.judge_enabled != judge_enabled:
            reasons.append("judge_enabled")
        model_changed = (previous.model != suite["model"]
                         or previous.provider != suite["provider"])
        baseline = {
            "baseline_id": previous.baseline_id,
            "compatible": not reasons,
            "metadata": previous.metadata(),
        }
        if reasons:
            return baseline, {
                "status": "incompatible", "metric_deltas": {},
                "judge_deltas": {}, "incompatibility_reason": reasons,
                "model_changed": model_changed,
            }

        metric_deltas = {
            name: self._delta(
                previous.deterministic_metrics.get(name).value
                if name in previous.deterministic_metrics else None,
                report["metrics"].get(name, {}).get("value"),
            )
            for name in DETERMINISTIC_COMPARISONS
        }
        judge_deltas = {}
        if judge_enabled:
            for name in (*DIMENSIONS, "overall_mean", "coverage"):
                current = (report["judge"]["coverage"] if name == "coverage" else
                           report["judge"]["overall_mean"] if name == "overall_mean" else
                           report["judge"]["per_dimension_mean"].get(name))
                judge_deltas[name] = self._delta(previous.judge_metrics.get(name), current)
        return baseline, {
            "status": "compared_model_changed" if model_changed else "compared",
            "metric_deltas": metric_deltas, "judge_deltas": judge_deltas,
            "incompatibility_reason": [], "model_changed": model_changed,
        }

    @staticmethod
    def _delta(previous: Optional[float], current: Optional[float]) -> dict:
        if previous is None or current is None:
            return {
                "baseline": previous, "current": current, "delta": None,
                "status": "unavailable",
            }
        change = current - previous
        status = ("regressed" if change < -REGRESSION_DROP else
                  "improved" if change > REGRESSION_DROP else "stable")
        return {
            "baseline": previous, "current": current, "delta": change,
            "status": status,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicitly promote a RootLens evaluation report.")
    parser.add_argument("promote", choices=["promote"])
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--approved-path", type=Path, default=Path(
        os.getenv("ROOTLENS_APPROVED_BASELINE_PATH", str(DEFAULT_APPROVED_PATH))))
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    record = BaselineStore(args.approved_path).promote(report)
    print(json.dumps({
        "baseline_id": record.baseline_id, "approved_path": str(args.approved_path),
        "snapshot_path": str(args.approved_path.parent / "history" /
                             f"{record.baseline_id}.json"),
    }))


if __name__ == "__main__":
    main()
