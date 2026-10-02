"""Stage 4 structure-only observations, separate from Stage 3 baseline metrics."""
from __future__ import annotations

from dataclasses import dataclass

from core.diagnosis_assembler import DiagnosisAssembler
from core.diagnosis_pipeline import DiagnosisOutcome
from core.diagnosis_validation import (
    HIGH_RISK_TERMS, DiagnosisValidationContext, DiagnosisValidationError,
    validate_incident_diagnosis,
)
from core.incident_diagnosis import DiagnosisBuildStatus, IncidentDiagnosis
from core.intent_recognizer import IntentResult
from evaluation.rootlens_metrics import Metric


@dataclass(frozen=True)
class StructuredObservation:
    case_id: str
    diagnosis_build_status: str
    diagnosis_schema_version: str | None
    structured_diagnosis: IncidentDiagnosis | None
    error_code: str | None
    assembler_called: bool
    assembler_latency_ms: float | None
    input_tokens: int | None
    output_tokens: int | None
    schema_valid: bool
    invalid_evidence_refs: int
    invalid_knowledge_refs: int
    cited_findings: int
    finding_count: int
    compliant_actions: int
    action_count: int
    approval_violations: int
    clarification_valid: bool | None
    degraded_match: bool | None

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "diagnosis_build_status": self.diagnosis_build_status,
            "diagnosis_schema_version": self.diagnosis_schema_version,
            "structured_diagnosis": (self.structured_diagnosis.model_dump(mode="json")
                                     if self.structured_diagnosis else None),
            "error_code": self.error_code,
            "assembler_called": self.assembler_called,
            "assembler_latency_ms": self.assembler_latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "schema_valid": self.schema_valid,
        }


def observe_structured(case_id: str, intent: IntentResult,
                       outcome: DiagnosisOutcome) -> StructuredObservation:
    build = outcome.diagnosis_build_result
    diagnosis = build.diagnosis
    mode = ("clarification" if outcome.clarification_required else
            "runbook" if intent.intent.value == "runbook_query" else "diagnosis")
    if diagnosis is None:
        return StructuredObservation(
            case_id=case_id, diagnosis_build_status=build.status.value,
            diagnosis_schema_version=None, structured_diagnosis=None,
            error_code=build.error_code,
            assembler_called=build.assembler_latency_ms is not None,
            assembler_latency_ms=build.assembler_latency_ms,
            input_tokens=build.input_tokens, output_tokens=build.output_tokens,
            schema_valid=False, invalid_evidence_refs=0, invalid_knowledge_refs=0,
            cited_findings=0, finding_count=0, compliant_actions=0, action_count=0,
            approval_violations=0,
            clarification_valid=False if mode == "clarification" else None,
            degraded_match=None,
        )
    if mode == "clarification":
        context = DiagnosisValidationContext(
            actual_mode="clarification", actual_intent=intent.intent.value,
            clarification_required=True,
        )
    else:
        context = DiagnosisAssembler._context(
            intent, outcome.result, outcome.bundle, outcome.knowledge, mode)

    valid = False
    if diagnosis is not None:
        try:
            validate_incident_diagnosis(diagnosis, context)
            valid = True
        except DiagnosisValidationError:
            pass
    allowed_evidence = set(context.allowed_evidence)
    allowed_knowledge = {
        (item.document_id, item.chunk_id, item.source_ref)
        for item in context.allowed_knowledge
    }
    invalid_evidence = invalid_knowledge = cited = findings = actions = compliant = violations = 0
    clarification_valid = None
    degraded_match = None
    if diagnosis:
        invalid_evidence += sum(
            item.evidence_id not in allowed_evidence or
            context.allowed_evidence.get(item.evidence_id) != item.source_type
            for item in diagnosis.evidence_refs)
        invalid_knowledge = sum(
            (item.document_id, item.chunk_id, item.source_ref) not in allowed_knowledge
            for item in diagnosis.knowledge_refs)
        findings = len(diagnosis.confirmed_findings)
        cited = sum(bool(item.evidence_ids) and set(item.evidence_ids) <= allowed_evidence
                    for item in diagnosis.confirmed_findings)
        invalid_evidence += sum(
            evidence_id not in allowed_evidence
            for item in (*diagnosis.confirmed_findings, *diagnosis.hypotheses)
            for evidence_id in item.evidence_ids)
        invalid_evidence += sum(
            evidence_id not in allowed_evidence
            for item in diagnosis.recommended_actions
            for evidence_id in item.related_evidence_ids)
        actions = len(diagnosis.recommended_actions)
        for action in diagnosis.recommended_actions:
            risky = any(term in action.action.casefold() for term in HIGH_RISK_TERMS)
            if (not risky or action.risk_level == "high" and action.requires_approval) and (
                action.risk_level != "high" or action.requires_approval):
                compliant += 1
            else:
                violations += 1
        if mode == "clarification":
            clarification_valid = (
                diagnosis.status == "clarification" and bool(diagnosis.clarification_question)
                and not diagnosis.confirmed_findings and not diagnosis.hypotheses
                and not diagnosis.recommended_actions)
        degraded_match = diagnosis.degraded == (
            context.other_degradation or any(
                state in {"failed", "degraded"}
                for state in context.actual_tool_status.values()))
    elif mode == "clarification":
        clarification_valid = False
    return StructuredObservation(
        case_id=case_id, diagnosis_build_status=build.status.value,
        diagnosis_schema_version=diagnosis.schema_version if diagnosis else None,
        structured_diagnosis=diagnosis, error_code=build.error_code,
        assembler_called=build.assembler_latency_ms is not None,
        assembler_latency_ms=build.assembler_latency_ms,
        input_tokens=build.input_tokens, output_tokens=build.output_tokens,
        schema_valid=valid, invalid_evidence_refs=invalid_evidence,
        invalid_knowledge_refs=invalid_knowledge, cited_findings=cited,
        finding_count=findings, compliant_actions=compliant, action_count=actions,
        approval_violations=violations, clarification_valid=clarification_valid,
        degraded_match=degraded_match,
    )


def score_structured(observations: list[StructuredObservation]) -> dict[str, Metric]:
    successful = [item for item in observations
                  if item.diagnosis_build_status == DiagnosisBuildStatus.SUCCESS.value]
    return {
        "diagnosis_build_success_rate": Metric(len(successful), len(observations)),
        "structured_schema_valid_rate": Metric(sum(item.schema_valid for item in successful),
                                               len(successful)),
        "invalid_evidence_ref_count": Metric(sum(item.invalid_evidence_refs for item in successful),
                                             len(observations), "count"),
        "invalid_knowledge_ref_count": Metric(sum(item.invalid_knowledge_refs for item in successful),
                                              len(observations), "count"),
        "confirmed_finding_source_coverage": Metric(
            sum(item.cited_findings for item in successful),
            sum(item.finding_count for item in successful)),
        "approval_policy_accuracy": Metric(
            sum(item.compliant_actions for item in successful),
            sum(item.action_count for item in successful)),
        "approval_policy_violation_count": Metric(
            sum(item.approval_violations for item in successful),
            len(observations), "count"),
        "clarification_structure_accuracy": Metric(
            sum(item.clarification_valid is True for item in observations),
            sum(item.clarification_valid is not None for item in observations)),
        "degraded_flag_accuracy": Metric(
            sum(item.degraded_match is True for item in successful),
            sum(item.degraded_match is not None for item in successful)),
    }


def structured_report(observations: list[StructuredObservation]) -> dict:
    metrics = score_structured(observations)
    return {
        "schema_version": "1",
        "metrics": {name: {"numerator": item.numerator,
                           "denominator": item.denominator, "value": item.value}
                    for name, item in metrics.items()},
        "observations": [item.to_dict() for item in observations],
    }
