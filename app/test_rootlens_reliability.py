"""Pure Stage 5 reliability scoring checks, independent of Judge and baseline."""
import json

from evaluation.rootlens_reliability import (
    ReliabilityReport, ReliabilityScenarioResult, score_reliability,
)


def scenario(**changes):
    values = dict(
        scenario_id="offline", injected_target="query_logs", injected_failure="timeout",
        observed_trace_status="failed", expected_overall_status="degraded",
        actual_overall_status="degraded", degraded_expected=True, degraded_actual=True,
        fallback_expected=None, fallback_observed=False, response_preserved=True,
        diagnosis_status="success", invalid_source_refs=[],
        assertions={"failure_detected": True, "degraded_flag": True,
                    "diagnosis_degraded": True, "containment": True},
        skipped_checks={}, expected_failure_step="query_logs", containment_required=True,
    )
    values.update(changes)
    return ReliabilityScenarioResult(**values)


def test_empty_suite_has_null_rates_not_invented_perfect_scores():
    report = ReliabilityReport([], score_reliability([])).to_dict()
    assert all(item == {"numerator": 0, "denominator": 0, "value": None}
               for item in report["metrics"].values())
    json.dumps(report)


def test_metric_denominators_and_negative_controls_are_explicit():
    failed = scenario(
        assertions={"failure_detected": False, "degraded_flag": True,
                    "diagnosis_degraded": False, "containment": False},
        invalid_source_refs=["UNSUPPORTED"],
    )
    normal = scenario(
        scenario_id="normal", injected_target=None, injected_failure=None,
        observed_trace_status=None, expected_failure_step=None,
        expected_overall_status="success", actual_overall_status="success",
        degraded_expected=False, degraded_actual=False,
        assertions={"degraded_flag": True, "containment": True},
        skipped_checks={"query_logs": True, "agent_execution": False},
    )
    metrics = ReliabilityReport([failed, normal],
                                score_reliability([failed, normal])).to_dict()["metrics"]
    assert metrics["failure_detection_accuracy"] == {
        "numerator": 0, "denominator": 1, "value": 0.0}
    assert metrics["degraded_flag_accuracy"] == {
        "numerator": 1, "denominator": 2, "value": 0.5}
    assert metrics["fallback_observed_accuracy"] == {
        "numerator": 0, "denominator": 0, "value": None}
    assert metrics["failure_containment_success_rate"] == {
        "numerator": 1, "denominator": 2, "value": 0.5}
    assert metrics["skipped_step_accuracy"] == {
        "numerator": 1, "denominator": 2, "value": 0.5}
    assert metrics["invalid_source_after_failure_count"] == {
        "numerator": 1, "denominator": 1, "value": 1}
