"""Stage 4 structured diagnosis contract; no runtime or LLM dependencies."""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]
DiagnosisMode = Literal["diagnosis", "runbook", "clarification"]
EvidenceSource = Literal["log", "metric", "deployment"]
ToolStatus = Literal["ok", "empty", "failed", "degraded"]
RiskLevel = Literal["low", "medium", "high"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EvidenceRef(Contract):
    evidence_id: Text
    source_type: EvidenceSource


class KnowledgeRef(Contract):
    document_id: Text
    chunk_id: Text
    source_ref: Text


class ConfirmedFinding(Contract):
    statement: Text
    evidence_ids: list[Text] = Field(min_length=1)


class Hypothesis(Contract):
    statement: Text
    evidence_ids: list[Text] = Field(default_factory=list)
    verification_steps: list[Text] = Field(min_length=1)


class RecommendedAction(Contract):
    action: Text
    reason: Text
    risk_level: RiskLevel
    requires_approval: bool
    related_evidence_ids: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def high_risk_requires_approval(self):
        if self.risk_level == "high" and not self.requires_approval:
            raise ValueError("high-risk actions require approval")
        return self


class EvidenceGap(Contract):
    description: Text
    why_needed: Text


class IncidentDiagnosis(Contract):
    schema_version: Literal["1"] = "1"
    status: DiagnosisMode
    summary: Text
    affected_services: list[Text] = Field(default_factory=list)
    environment: Text | None = None
    intent: Text
    primary_agent: Text | None = None
    supporting_agents: list[Text] = Field(default_factory=list)
    confirmed_findings: list[ConfirmedFinding] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    knowledge_refs: list[KnowledgeRef] = Field(default_factory=list)
    tool_status: dict[Text, ToolStatus] = Field(default_factory=dict)
    degraded: bool = False
    requires_approval: bool = False
    clarification_required: bool = False
    clarification_question: Text | None = None

    @model_validator(mode="after")
    def consistent_mode_and_approval(self):
        if self.requires_approval != any(action.requires_approval
                                         for action in self.recommended_actions):
            raise ValueError("top-level approval must match recommended actions")
        if self.status == "clarification":
            if not self.clarification_required or not self.clarification_question:
                raise ValueError("clarification needs a question")
            if (self.confirmed_findings or self.hypotheses or self.recommended_actions
                    or self.evidence_refs or self.knowledge_refs or self.tool_status
                    or self.primary_agent or self.supporting_agents):
                raise ValueError("clarification cannot contain diagnosis or tool output")
        elif self.clarification_required or self.clarification_question is not None:
            raise ValueError("only clarification may ask a clarification question")
        if self.status == "runbook" and self.confirmed_findings:
            raise ValueError("runbook knowledge is not a confirmed incident finding")
        return self


class DiagnosisBuildStatus(str, Enum):
    NOT_RUN = "not_run"
    SUCCESS = "success"
    VALIDATION_FAILED = "validation_failed"
    PARSE_FAILED = "parse_failed"
    ASSEMBLER_FAILED = "assembler_failed"


class DiagnosisBuildResult(Contract):
    status: DiagnosisBuildStatus
    diagnosis: IncidentDiagnosis | None = None
    error_code: Text | None = None
    assembler_latency_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def fail_closed(self):
        if self.status == DiagnosisBuildStatus.SUCCESS:
            if self.diagnosis is None or self.error_code is not None:
                raise ValueError("success requires a diagnosis and no error")
        elif self.status == DiagnosisBuildStatus.NOT_RUN:
            if self.diagnosis is not None or self.error_code is not None:
                raise ValueError("not_run cannot contain a diagnosis or error")
        elif self.diagnosis is not None or self.error_code is None:
            raise ValueError("failure requires an error code and no diagnosis")
        return self
