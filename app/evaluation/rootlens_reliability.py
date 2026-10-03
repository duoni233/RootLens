"""Stage 5 deterministic reliability observations, separate from Stage 3 metrics."""
from __future__ import annotations

from dataclasses import dataclass, field

from core.diagnosis_pipeline import DiagnosisOutcome
from evaluation.rootlens_metrics import Metric


@dataclass(frozen=True)
class ReliabilityExpectation:
    overall_status: str
    degraded: bool
    diagnosis_status: str
    failure_step: str | None = None
    expected_error_code: str | None = None
    failure_role: str | None = None
    fallback: bool | None = None
    diagnosis_degraded: bool | None = None
    unaffected_steps: tuple[str, ...] = ()
    skipped_steps: tuple[str, ...] = ()
    response_contains: str | None = None
    containment_required: bool = True


@dataclass
class ReliabilityScenarioResult:
    scenario_id: str
    injected_target: str | None
    injected_failure: str | None
    observed_trace_status: str | None
    expected_overall_status: str
    actual_overall_status: str | None
    degraded_expected: bool
    degraded_actual: bool
    fallback_expected: bool | None
    fallback_observed: bool
    response_preserved: bool
    diagnosis_status: str
    invalid_source_refs: list[str] = field(default_factory=list)
    assertions: dict[str, bool] = field(default_factory=dict)
    skipped_checks: dict[str, bool] = field(default_factory=dict)
    expected_failure_step: str | None = None
    containment_required: bool = True

    @property
    def passed(self) -> bool:
        return all(self.assertions.values())


@dataclass
class ReliabilityReport:
    scenarios: list[ReliabilityScenarioResult]
    metrics: dict[str, Metric]
    suite_name: str = "rootlens-stage5-reliability"
    suite_version: str = "stage5-v1"

    def to_dict(self) -> dict:
        return {
            "suite_name": self.suite_name, "suite_version": self.suite_version,
            "scenarios": [{
                key: value for key, value in vars(item).items()
            } for item in self.scenarios],
            "metrics": {name: {"numerator": item.numerator,
                               "denominator": item.denominator, "value": item.value}
                        for name, item in self.metrics.items()},
        }


def _fallback_seen(outcome: DiagnosisOutcome) -> bool:
    trace = outcome.trace
    if trace is None:
        return False
    attempts = [step for step in trace.steps if step.step_type == "agent_execution"]
    for index, step in enumerate(attempts):
        requested = step.metadata.get("requested_agent")
        if step.status != "failed" or not requested:
            continue
        if any(later.metadata.get("requested_agent") == requested
               and later.metadata.get("executed_agent") == "general_ops"
               and later.status in {"success", "degraded"}
               for later in attempts[index + 1:]):
            return True
    return False


def _invalid_refs(outcome: DiagnosisOutcome) -> list[str]:
    allowed_evidence = {item.evidence_id for item in outcome.bundle.evidence} if outcome.bundle else set()
    allowed_knowledge = {(item.document_id, item.chunk_id, item.source_ref)
                         for item in outcome.knowledge.sources}
    invalid = []
    diagnosis = outcome.diagnosis_build_result.diagnosis
    if diagnosis is not None:
        invalid.extend(ref.evidence_id for ref in diagnosis.evidence_refs
                       if ref.evidence_id not in allowed_evidence)
        invalid.extend(ref.chunk_id for ref in diagnosis.knowledge_refs
                       if (ref.document_id, ref.chunk_id, ref.source_ref) not in allowed_knowledge)
    if outcome.trace:
        for step in outcome.trace.steps:
            if step.status == "failed" and step.step_type in {
                "query_logs", "query_metrics", "query_deployments", "rag_retrieval",
            }:
                invalid.extend(step.evidence_ids)
                invalid.extend(step.knowledge_ids)
    return invalid


def observe_reliability(*, scenario_id: str, outcome: DiagnosisOutcome,
                        expected: ReliabilityExpectation,
                        injected_target: str | None = None,
                        injected_failure: str | None = None) -> ReliabilityScenarioResult:
    """Compare expectations only after the runtime diagnosis has completed."""
    trace = outcome.trace
    if trace is None:
        raise ValueError("reliability observation requires an execution trace")
    candidates = [step for step in trace.steps if step.step_type == expected.failure_step]
    if expected.failure_role:
        candidates = [step for step in candidates
                      if step.metadata.get("role") == expected.failure_role]
    observed = next((step for step in candidates
                     if step.status in {"failed", "degraded"}), None)
    failure_detected = (observed is not None and
                        (expected.expected_error_code is None or
                         observed.error_code == expected.expected_error_code))
    skipped = {name: any(step.step_type == name and step.status == "skipped"
                         for step in trace.steps) for name in expected.skipped_steps}
    unaffected = all(any(step.step_type == name and step.status == "success"
                         for step in trace.steps) for name in expected.unaffected_steps)
    response_preserved = bool(outcome.result.response) and (
        expected.response_contains is None or
        expected.response_contains in outcome.result.response)
    invalid = _invalid_refs(outcome)
    diagnosis = outcome.diagnosis_build_result.diagnosis
    actual_build_status = outcome.diagnosis_build_result.status.value
    fallback = _fallback_seen(outcome)
    assertions = {
        "overall_status": trace.overall_status == expected.overall_status,
        "degraded_flag": trace.degraded == expected.degraded,
        "diagnosis_status": actual_build_status == expected.diagnosis_status,
        "response_preserved": response_preserved,
        "unaffected_steps": unaffected,
        "invalid_source_refs": not invalid,
        "skipped_steps": all(skipped.values()),
    }
    if expected.failure_step is not None:
        assertions["failure_detected"] = failure_detected
    if expected.fallback is not None:
        assertions["fallback"] = fallback == expected.fallback
    if expected.diagnosis_degraded is not None:
        assertions["diagnosis_degraded"] = (
            diagnosis is not None and diagnosis.degraded == expected.diagnosis_degraded)
    assertions["containment"] = (
        response_preserved and unaffected and not invalid and
        assertions["overall_status"] and assertions["degraded_flag"] and
        assertions["diagnosis_status"] and
        assertions.get("diagnosis_degraded", True) and
        assertions.get("failure_detected", True) and
        assertions.get("fallback", True) and
        assertions["skipped_steps"])
    return ReliabilityScenarioResult(
        scenario_id=scenario_id, injected_target=injected_target,
        injected_failure=injected_failure,
        observed_trace_status=observed.status if observed else None,
        expected_overall_status=expected.overall_status,
        actual_overall_status=trace.overall_status,
        degraded_expected=expected.degraded, degraded_actual=trace.degraded,
        fallback_expected=expected.fallback, fallback_observed=fallback,
        response_preserved=response_preserved, diagnosis_status=actual_build_status,
        invalid_source_refs=invalid, assertions=assertions, skipped_checks=skipped,
        expected_failure_step=expected.failure_step,
        containment_required=expected.containment_required,
    )


def score_reliability(results: list[ReliabilityScenarioResult]) -> dict[str, Metric]:
    def accuracy(values: list[bool]) -> Metric:
        return Metric(sum(values), len(values))

    injected = [case for case in results if case.expected_failure_step is not None]
    fallback = [case for case in results if case.fallback_expected is True]
    contained = [case for case in results if case.containment_required]
    skipped = [ok for case in results for ok in case.skipped_checks.values()]
    return {
        "failure_detection_accuracy": accuracy([
            case.assertions.get("failure_detected", False) for case in injected]),
        "degraded_flag_accuracy": accuracy([
            case.assertions["degraded_flag"] and
            case.assertions.get("diagnosis_degraded", True) for case in results]),
        "fallback_observed_accuracy": accuracy([
            case.assertions.get("fallback", False) for case in fallback]),
        "failure_containment_success_rate": accuracy([
            case.assertions["containment"] for case in contained]),
        "skipped_step_accuracy": accuracy(skipped),
        "invalid_source_after_failure_count": Metric(
            sum(len(case.invalid_source_refs) for case in injected),
            len(injected), aggregation="count"),
    }
