"""Pure, run-scoped validation for IncidentDiagnosis v1."""
from __future__ import annotations

from pydantic import Field

from core.incident_diagnosis import (
    Contract, DiagnosisMode, EvidenceSource, IncidentDiagnosis, KnowledgeRef,
    Text, ToolStatus,
)


HIGH_RISK_TERMS = (
    "rollback", "回滚", "restart", "重启", "扩容", "限流", "清库",
    "生产配置", "truncate", "delete from",
)


class DiagnosisValidationError(ValueError):
    """A diagnosis disagrees with facts supplied by this specific run."""


class DiagnosisValidationContext(Contract):
    actual_mode: DiagnosisMode
    actual_intent: Text
    actual_primary_agent: Text | None = None
    actual_supporting_agents: list[Text] = Field(default_factory=list)
    known_agents: frozenset[Text] = frozenset()
    allowed_services: frozenset[Text] = frozenset()
    actual_environment: Text | None = None
    allowed_evidence: dict[Text, EvidenceSource] = Field(default_factory=dict)
    allowed_knowledge: list[KnowledgeRef] = Field(default_factory=list)
    actual_tool_status: dict[Text, ToolStatus] = Field(default_factory=dict)
    clarification_required: bool = False
    other_degradation: bool = False


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise DiagnosisValidationError(reason)


def _unique(values: list[str], reason: str) -> None:
    _require(len(values) == len(set(values)), reason)


def _knowledge_key(item: KnowledgeRef) -> tuple[str, str, str]:
    return item.document_id, item.chunk_id, item.source_ref


def validate_incident_diagnosis(
    diagnosis: IncidentDiagnosis, context: DiagnosisValidationContext,
) -> IncidentDiagnosis:
    """Validate provenance and control fields, not semantic entailment of prose."""
    _require(diagnosis.status == context.actual_mode, "status differs from observed mode")
    _require(diagnosis.intent == context.actual_intent, "intent differs from observed intent")
    _require(diagnosis.clarification_required == context.clarification_required,
             "clarification differs from observed state")
    _require(diagnosis.environment == context.actual_environment,
             "environment differs from query context")

    _unique(diagnosis.affected_services, "duplicate service")
    _require(set(diagnosis.affected_services) <= context.allowed_services,
             "unknown affected service")
    _unique(diagnosis.supporting_agents, "duplicate supporting agent")
    actual_agents = ([context.actual_primary_agent] if context.actual_primary_agent else [])
    actual_agents += context.actual_supporting_agents
    _require(set(actual_agents) <= context.known_agents, "unknown actual agent")
    _require(diagnosis.primary_agent == context.actual_primary_agent
             and diagnosis.supporting_agents == context.actual_supporting_agents,
             "agents differ from actual routing")

    refs = {item.evidence_id: item.source_type for item in diagnosis.evidence_refs}
    _require(len(refs) == len(diagnosis.evidence_refs), "duplicate evidence ref")
    _require(refs == context.allowed_evidence, "evidence refs differ from this run")
    knowledge = {_knowledge_key(item) for item in diagnosis.knowledge_refs}
    allowed_knowledge = {_knowledge_key(item) for item in context.allowed_knowledge}
    _require(len(knowledge) == len(diagnosis.knowledge_refs), "duplicate knowledge ref")
    _require(knowledge == allowed_knowledge, "knowledge refs differ from this run")

    for finding in diagnosis.confirmed_findings:
        _unique(finding.evidence_ids, "duplicate finding citation")
        _require(bool(finding.evidence_ids), "finding requires operational evidence")
        _require(set(finding.evidence_ids) <= refs.keys(), "unknown finding evidence")
    for hypothesis in diagnosis.hypotheses:
        _unique(hypothesis.evidence_ids, "duplicate hypothesis citation")
        _require(set(hypothesis.evidence_ids) <= refs.keys(), "unknown hypothesis evidence")
    for action in diagnosis.recommended_actions:
        _unique(action.related_evidence_ids, "duplicate action citation")
        _require(set(action.related_evidence_ids) <= refs.keys(), "unknown action evidence")
        if any(term in action.action.casefold() for term in HIGH_RISK_TERMS):
            _require(action.risk_level == "high" and action.requires_approval,
                     "production change requires high risk and approval")

    _require(diagnosis.tool_status == context.actual_tool_status,
             "tool status differs from this run")
    expected_degraded = context.other_degradation or any(
        status in {"failed", "degraded"} for status in context.actual_tool_status.values()
    )
    _require(diagnosis.degraded == expected_degraded, "degraded flag differs from this run")
    return diagnosis
