"""Deterministic Stage 3 metrics; this module never invokes a model or runtime tool."""
from __future__ import annotations

from dataclasses import dataclass

from evaluation.rootlens_cases import EvaluationCase, EvaluationObservation


@dataclass(frozen=True)
class Metric:
    numerator: float
    denominator: int
    aggregation: str = "rate"

    @property
    def value(self) -> float | None:
        if not self.denominator:
            return None
        return self.numerator if self.aggregation == "count" else self.numerator / self.denominator


def _metric(values: list[float]) -> Metric:
    return Metric(sum(values), len(values))


def score_cases(cases: list[EvaluationCase],
                observations: list[EvaluationObservation]) -> dict[str, Metric]:
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("duplicate evaluation case IDs")
    if len({item.case_id for item in observations}) != len(observations):
        raise ValueError("duplicate observation case IDs")
    actual = {item.case_id: item for item in observations}
    if set(actual) - {case.case_id for case in cases}:
        raise ValueError("observation has no matching case")

    intent_pairs = []
    primary, exact, partial, evidence, tool, clarify, runbook, forbidden = (
        [] for _ in range(8))
    for case in cases:
        expected = case.expected
        observed = actual.get(case.case_id)
        if expected.intent is not None:
            intent_pairs.append((expected.intent, observed.intent if observed else None))
        if expected.primary_agent is not None:
            primary.append(float(observed is not None and
                                 expected.primary_agent == observed.primary_agent))
        if expected.supporting_agents is not None:
            wanted = set(expected.supporting_agents)
            got = set(observed.supporting_agents or []) if observed else set()
            exact.append(float(observed is not None and wanted == got))
            partial.append(len(wanted & got) / len(wanted | got) if wanted | got
                           else float(observed is not None))
        if expected.evidence_ids is not None:
            got = set(observed.evidence_ids or []) if observed else set()
            evidence.extend(float(item in got) for item in set(expected.evidence_ids))
        if expected.tool_status is not None:
            got = observed.tool_status or {} if observed else {}
            tool.append(float(observed is not None and got == expected.tool_status))
        if expected.clarification_required is not None:
            clarify.append(float(observed is not None and
                                 expected.clarification_required == observed.clarification_required))
        if expected.runbook_ids:
            got = set(observed.runbook_ids or []) if observed else set()
            runbook.append(float(set(expected.runbook_ids) <= got))
        if expected.forbidden_claims:
            answer = (observed.response or "").casefold() if observed else ""
            forbidden.extend(float(bool(answer) and phrase.casefold() in answer)
                             for phrase in expected.forbidden_claims)

    labels = {label for pair in intent_pairs for label in pair if label is not None}
    f1s = []
    for label in labels:
        tp = sum(exp == label and pred == label for exp, pred in intent_pairs)
        fp = sum(exp != label and pred == label for exp, pred in intent_pairs)
        fn = sum(exp == label and pred != label for exp, pred in intent_pairs)
        f1s.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0)

    return {
        "intent_accuracy": Metric(sum(exp == pred for exp, pred in intent_pairs), len(intent_pairs)),
        "intent_macro_f1": _metric(f1s),
        "primary_agent_accuracy": _metric(primary),
        "supporting_agent_exact_match": _metric(exact),
        "supporting_agent_partial_match": _metric(partial),
        "evidence_required_coverage": _metric(evidence),
        "tool_status_accuracy": _metric(tool),
        "clarification_accuracy": _metric(clarify),
        "runbook_hit_accuracy": _metric(runbook),
        "forbidden_claim_violation_count": Metric(
            sum(forbidden), len(forbidden), aggregation="count"),
    }
