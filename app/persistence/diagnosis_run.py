"""Versioned, allowlisted snapshot of one completed runtime diagnosis."""
from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from core.incident_diagnosis import (
    DiagnosisBuildStatus, EvidenceRef, IncidentDiagnosis, KnowledgeRef,
)
from core.diagnosis_trace import DiagnosisTrace, OverallStatus


class DiagnosisRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"] = "1"
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    trace_id: str | None = None
    request_id: str | None = None
    conversation_id: str | None = None
    created_at: AwareDatetime
    completed_at: AwareDatetime
    original_message: str
    service_name: str | None = None
    environment: str | None = None
    intent: str
    primary_agent: str | None = None
    supporting_agents: list[str] = Field(default_factory=list)
    response_markdown: str
    diagnosis_status: DiagnosisBuildStatus
    trace_status: OverallStatus | None = None
    degraded: bool = False
    clarification_required: bool = False
    diagnosis: IncidentDiagnosis | None = None
    trace: DiagnosisTrace | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    knowledge_refs: list[KnowledgeRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_snapshots(self):
        if self.completed_at < self.created_at:
            raise ValueError("completed_at precedes created_at")
        if self.trace is not None:
            if self.trace_id != self.trace.trace_id:
                raise ValueError("trace_id does not match trace snapshot")
            if self.trace.eval_run_id is not None:
                raise ValueError("evaluation traces cannot enter runtime history")
        elif self.trace_id is not None:
            raise ValueError("trace_id requires a trace snapshot")
        if (self.diagnosis_status == DiagnosisBuildStatus.SUCCESS) != (self.diagnosis is not None):
            raise ValueError("diagnosis snapshot must match build status")
        return self
