"""Stage 4-1 contract tests; all examples are deterministic and offline."""
import pytest
from pydantic import ValidationError

from core.diagnosis_validation import (
    DiagnosisValidationContext, DiagnosisValidationError,
    validate_incident_diagnosis,
)
from core.incident_diagnosis import (
    DiagnosisBuildResult, DiagnosisBuildStatus, IncidentDiagnosis,
    KnowledgeRef,
)


LOG = "rootlens-demo:v1:INC-001:log:L001"
METRIC = "rootlens-demo:v1:INC-001:metric:M003"
DEPLOYMENT = "rootlens-demo:v1:INC-001:deployment:D001"
RUNBOOK = {
    "document_id": "RL-RB-DB-001",
    "chunk_id": "RL-RB-DB-001:c0000",
    "source_ref": "knowledge/rootlens/db-connection-pool.md",
}


def normal_data(**changes):
    data = {
        "status": "diagnosis", "summary": "The connection pool reached its limit.",
        "affected_services": ["payment-service"], "environment": "demo",
        "intent": "deployment_issue", "primary_agent": "application",
        "supporting_agents": ["database"],
        "confirmed_findings": [{
            "statement": "Connection acquisition failed while the pool was full.",
            "evidence_ids": [LOG, METRIC],
        }],
        "hypotheses": [{
            "statement": "v2.3.7 may have introduced a connection leak.",
            "evidence_ids": [DEPLOYMENT],
            "verification_steps": ["Compare v2.3.6 with v2.3.7."],
        }],
        "recommended_actions": [{
            "action": "Evaluate rollback after stronger evidence.",
            "reason": "The release precedes the incident but causation is unproven.",
            "risk_level": "high", "requires_approval": True,
            "related_evidence_ids": [DEPLOYMENT],
        }],
        "evidence_gaps": [{
            "description": "No database-side latency metrics.",
            "why_needed": "They distinguish a slow DB from a client leak.",
        }],
        "evidence_refs": [
            {"evidence_id": LOG, "source_type": "log"},
            {"evidence_id": METRIC, "source_type": "metric"},
            {"evidence_id": DEPLOYMENT, "source_type": "deployment"},
        ],
        "knowledge_refs": [RUNBOOK],
        "tool_status": {"query_logs": "ok", "query_metrics": "ok",
                        "query_deployments": "ok"},
        "degraded": False, "requires_approval": True,
        "clarification_required": False,
    }
    data.update(changes)
    return data


def normal_context(**changes):
    data = {
        "actual_mode": "diagnosis", "actual_intent": "deployment_issue",
        "actual_primary_agent": "application", "actual_supporting_agents": ["database"],
        "known_agents": frozenset({"application", "database", "infrastructure"}),
        "allowed_services": frozenset({"payment-service"}),
        "actual_environment": "demo",
        "allowed_evidence": {LOG: "log", METRIC: "metric", DEPLOYMENT: "deployment"},
        "allowed_knowledge": [KnowledgeRef(**RUNBOOK)],
        "actual_tool_status": {"query_logs": "ok", "query_metrics": "ok",
                               "query_deployments": "ok"},
        "clarification_required": False,
    }
    data.update(changes)
    return DiagnosisValidationContext(**data)


def validate(data=None, context=None):
    diagnosis = IncidentDiagnosis(**(data or normal_data()))
    return validate_incident_diagnosis(diagnosis, context or normal_context())


def test_inc001_normal_contract_and_json_round_trip():
    diagnosis = validate()
    assert diagnosis.schema_version == "1"
    assert diagnosis.requires_approval
    assert IncidentDiagnosis.model_validate_json(diagnosis.model_dump_json()) == diagnosis


@pytest.mark.parametrize("changes", [
    {"confirmed_findings": [{"statement": "pool full", "evidence_ids": []}]},
    {"schema_version": "2"},
    {"extra_field": "not allowed"},
    {"affected_services": "payment-service"},
    {"summary": "  "},
])
def test_malformed_contract_is_rejected_by_pydantic(changes):
    with pytest.raises(ValidationError):
        IncidentDiagnosis(**normal_data(**changes))


@pytest.mark.parametrize("where", ["finding", "hypothesis", "action"])
def test_unknown_nested_evidence_citation_is_rejected(where):
    changes = {}
    if where == "finding":
        changes["confirmed_findings"] = [{"statement": "pool full", "evidence_ids": ["FAKE"]}]
    elif where == "hypothesis":
        changes["hypotheses"] = [{
            "statement": "possible leak", "evidence_ids": ["FAKE"],
            "verification_steps": ["check pool usage"],
        }]
    else:
        action = dict(normal_data()["recommended_actions"][0])
        action["related_evidence_ids"] = ["FAKE"]
        changes["recommended_actions"] = [action]
    with pytest.raises(DiagnosisValidationError, match="unknown"):
        validate(normal_data(**changes))


def test_hypothesis_without_operational_citation_is_allowed():
    hypothesis = dict(normal_data()["hypotheses"][0], evidence_ids=[])
    assert validate(normal_data(hypotheses=[hypothesis])).hypotheses[0].evidence_ids == []


def test_unknown_or_spoofed_evidence_ref_is_rejected():
    refs = normal_data()["evidence_refs"]
    for bad in ({"evidence_id": "FAKE", "source_type": "log"},
                {"evidence_id": LOG, "source_type": "metric"}):
        with pytest.raises(DiagnosisValidationError, match="evidence refs"):
            validate(normal_data(evidence_refs=[bad, *refs[1:]]))


def test_unknown_knowledge_id_or_source_is_rejected():
    for change in ({"document_id": "FAKE"}, {"source_ref": "knowledge/other.md"}):
        with pytest.raises(DiagnosisValidationError, match="knowledge refs"):
            validate(normal_data(knowledge_refs=[{**RUNBOOK, **change}]))


def test_unknown_service_is_rejected():
    with pytest.raises(DiagnosisValidationError, match="unknown affected service"):
        validate(normal_data(affected_services=["fictional-service"]))


@pytest.mark.parametrize("change", [
    {"primary_agent": "fictional-agent"},
    {"supporting_agents": ["infrastructure"]},
    {"supporting_agents": ["fictional-agent"]},
])
def test_agents_must_match_actual_route(change):
    with pytest.raises(DiagnosisValidationError, match="agents differ"):
        validate(normal_data(**change))


def test_high_risk_action_requires_approval_and_top_level_propagates():
    action = dict(normal_data()["recommended_actions"][0])
    with pytest.raises(ValidationError, match="high-risk"):
        IncidentDiagnosis(**normal_data(recommended_actions=[{
            **action, "requires_approval": False,
        }], requires_approval=False))
    with pytest.raises(ValidationError, match="top-level approval"):
        IncidentDiagnosis(**normal_data(requires_approval=False))
    with pytest.raises(ValidationError, match="top-level approval"):
        IncidentDiagnosis(**normal_data(recommended_actions=[], requires_approval=True))
    assert validate().requires_approval


def test_production_change_text_cannot_be_labeled_low_risk():
    action = dict(normal_data()["recommended_actions"][0], risk_level="low")
    with pytest.raises(DiagnosisValidationError, match="production change"):
        validate(normal_data(recommended_actions=[action]))


def clarification_data(**changes):
    data = {
        "status": "clarification", "summary": "The affected service is missing.",
        "intent": "service_incident", "clarification_required": True,
        "clarification_question": "Please provide the affected service name.",
    }
    data.update(changes)
    return data


def clarification_context(**changes):
    data = {
        "actual_mode": "clarification", "actual_intent": "service_incident",
        "clarification_required": True,
    }
    data.update(changes)
    return DiagnosisValidationContext(**data)


def test_clarification_has_no_diagnosis_or_production_action():
    diagnosis = IncidentDiagnosis(**clarification_data())
    assert validate_incident_diagnosis(diagnosis, clarification_context()) == diagnosis
    assert diagnosis.confirmed_findings == diagnosis.hypotheses == []
    assert diagnosis.recommended_actions == []


@pytest.mark.parametrize("change", [
    {"confirmed_findings": [{"statement": "pool full", "evidence_ids": [LOG]}]},
    {"hypotheses": [{"statement": "leak", "verification_steps": ["check logs"]}]},
    {"recommended_actions": [{"action": "restart", "reason": "mitigation",
                             "risk_level": "high", "requires_approval": True}]},
    {"clarification_question": None},
    {"clarification_required": False},
    {"status": "diagnosis"},
])
def test_invalid_clarification_is_rejected(change):
    with pytest.raises(ValidationError):
        IncidentDiagnosis(**clarification_data(**change))


def test_runbook_only_without_operational_evidence():
    diagnosis = IncidentDiagnosis(
        status="runbook", summary="Review the connection-pool runbook.",
        intent="runbook_query", primary_agent="database",
        knowledge_refs=[RUNBOOK],
        recommended_actions=[{
            "action": "Inspect pool usage and wait time.", "reason": "Distinguish saturation.",
            "risk_level": "low", "requires_approval": False,
        }],
    )
    context = DiagnosisValidationContext(
        actual_mode="runbook", actual_intent="runbook_query",
        actual_primary_agent="database", known_agents=frozenset({"database"}),
        allowed_knowledge=[KnowledgeRef(**RUNBOOK)],
    )
    assert validate_incident_diagnosis(diagnosis, context) == diagnosis
    with pytest.raises(ValidationError, match="not a confirmed incident"):
        IncidentDiagnosis(**{
            **diagnosis.model_dump(),
            "confirmed_findings": [{"statement": "pool full", "evidence_ids": [LOG]}],
        })


@pytest.mark.parametrize("status,degraded", [
    ("empty", False), ("failed", True), ("degraded", True),
])
def test_tool_state_and_degraded_are_not_conflated(status, degraded):
    data = normal_data(
        confirmed_findings=[], hypotheses=[], recommended_actions=[],
        requires_approval=False, evidence_refs=[], knowledge_refs=[],
        tool_status={"query_logs": status}, degraded=degraded,
    )
    context = normal_context(
        allowed_evidence={}, allowed_knowledge=[],
        actual_tool_status={"query_logs": status},
    )
    assert validate(data, context).degraded is degraded
    with pytest.raises(DiagnosisValidationError, match="degraded flag"):
        validate({**data, "degraded": not degraded}, context)


def test_non_tool_degradation_must_be_explicit_in_context():
    data = normal_data(degraded=True)
    context = normal_context(other_degradation=True)
    assert validate(data, context).degraded


def test_observed_intent_mode_environment_and_tool_state_cannot_be_invented():
    changes = (
        ({"intent": "other"}, "intent differs"),
        ({"status": "runbook", "confirmed_findings": []}, "status differs"),
        ({"environment": "prod"}, "environment differs"),
        ({"tool_status": {"query_logs": "empty"}}, "tool status differs"),
    )
    for change, reason in changes:
        with pytest.raises(DiagnosisValidationError, match=reason):
            validate(normal_data(**change))


def test_build_result_never_mislabels_a_failure_as_success():
    diagnosis = validate()
    assert DiagnosisBuildResult(status=DiagnosisBuildStatus.SUCCESS,
                                diagnosis=diagnosis).diagnosis == diagnosis
    assert DiagnosisBuildResult(status=DiagnosisBuildStatus.NOT_RUN).diagnosis is None
    failed = DiagnosisBuildResult(status=DiagnosisBuildStatus.PARSE_FAILED,
                                  error_code="invalid_json")
    assert failed.diagnosis is None
    with pytest.raises(ValidationError):
        DiagnosisBuildResult(status=DiagnosisBuildStatus.SUCCESS)
    with pytest.raises(ValidationError):
        DiagnosisBuildResult(status=DiagnosisBuildStatus.VALIDATION_FAILED,
                             diagnosis=diagnosis, error_code="invalid_ref")
