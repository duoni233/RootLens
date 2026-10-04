"""Public history response shapes; full Trace has its own guarded endpoint."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from core.incident_diagnosis import DiagnosisBuildStatus, EvidenceRef, IncidentDiagnosis, KnowledgeRef
from core.diagnosis_trace import OverallStatus
from persistence.diagnosis_run import DiagnosisRun


class HistorySummary(BaseModel):
    run_id: str
    created_at: datetime
    service_name: str | None
    intent: str
    primary_agent: str | None
    diagnosis_status: DiagnosisBuildStatus
    degraded: bool
    clarification_required: bool

    @classmethod
    def from_run(cls, run: DiagnosisRun) -> "HistorySummary":
        return cls.model_validate(run.model_dump())


class HistoryPage(BaseModel):
    items: list[HistorySummary] = Field(default_factory=list)
    limit: int
    offset: int


class HistoryDetail(HistorySummary):
    schema_version: str
    trace_id: str | None
    request_id: str | None
    conversation_id: str | None
    completed_at: datetime
    original_message: str
    environment: str | None
    supporting_agents: list[str]
    response_markdown: str
    trace_status: OverallStatus | None
    diagnosis: IncidentDiagnosis | None
    evidence_refs: list[EvidenceRef]
    knowledge_refs: list[KnowledgeRef]

    @classmethod
    def from_run(cls, run: DiagnosisRun) -> "HistoryDetail":
        return cls.model_validate(run.model_dump(exclude={"trace"}))
