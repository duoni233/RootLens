"""Project a completed diagnosis into an allowlisted history record."""
from __future__ import annotations

from datetime import datetime, timezone

from core.diagnosis_entry import RecognizedDiagnosis
from core.incident_diagnosis import EvidenceRef, KnowledgeRef
from persistence.diagnosis_run import DiagnosisRun


def build_diagnosis_run(*, diagnosis: RecognizedDiagnosis, message: str,
                        conversation_id: str | None = None,
                        environment: str | None = None) -> DiagnosisRun:
    outcome = diagnosis.outcome
    result = outcome.result
    trace = outcome.trace
    if trace is not None and trace.eval_run_id is not None:
        raise ValueError("evaluation executions cannot enter runtime diagnosis history")

    now = datetime.now(timezone.utc)
    service_names = diagnosis.intent.entities.get("service_name") or []
    bundle = outcome.bundle
    build_result = outcome.diagnosis_build_result
    structured = build_result.diagnosis
    tool_degraded = bool(bundle and any(
        item.status in {"failed", "degraded"} for item in bundle.tool_status.values()))
    agent_degraded = any(item.degraded for item in result.agent_executions)
    return DiagnosisRun(
        trace_id=trace.trace_id if trace else None,
        request_id=result.request_id or (trace.request_id if trace else None),
        conversation_id=conversation_id,
        created_at=trace.started_at if trace else now,
        completed_at=trace.completed_at if trace and trace.completed_at else now,
        original_message=message,
        service_name=service_names[0] if service_names else None,
        environment=environment or (bundle.query_context.environment if bundle else None),
        intent=diagnosis.intent.intent.value,
        primary_agent=(result.primary_agent.value if result.primary_agent else
                       None if outcome.clarification_required else result.agent_type.value),
        supporting_agents=[agent.value for agent in result.supporting_agents],
        response_markdown=result.response,
        diagnosis_status=build_result.status,
        trace_status=trace.overall_status if trace else None,
        degraded=bool((trace and trace.degraded) or (structured and structured.degraded)
                      or tool_degraded or agent_degraded),
        clarification_required=outcome.clarification_required,
        diagnosis=structured, trace=trace,
        evidence_refs=[EvidenceRef(evidence_id=item.evidence_id,
                                   source_type=item.source_type)
                       for item in bundle.evidence] if bundle else [],
        knowledge_refs=[KnowledgeRef(document_id=item.document_id,
                                     chunk_id=item.chunk_id,
                                     source_ref=item.source_ref)
                        for item in outcome.knowledge.sources],
    )
