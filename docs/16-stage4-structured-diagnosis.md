# Stage 4-1: Structured Diagnosis Contract

Status: contract and offline validation only. `IncidentDiagnosis` is not yet produced by
`DiagnosisPipeline`, `/chat`, or Evaluation. No Agent execution, routing, RAG,
Evidence Tool, Judge, or Stage 3 baseline behavior changes in this batch.

## IncidentDiagnosis v1

`app/core/incident_diagnosis.py` defines a strict Pydantic v2 contract with
`schema_version="1"` and three modes: `diagnosis`, `runbook`, `clarification`.
`degraded` is an independent Boolean; `status="diagnosis", degraded=true`
is valid when an upstream component failed or degraded.

| Fields | Meaning and future source |
| --- | --- |
| `status`, `intent`, `primary_agent`, `supporting_agents`, `affected_services`, `environment` | Observed mode, recognized intent, actual routing, validated service/environment. The model must not invent these. |
| `summary`, `confirmed_findings`, `hypotheses`, `recommended_actions`, `evidence_gaps` | Semantic synthesis of existing Agent outputs; not automatically filled in Stage 4-1. |
| `evidence_refs`, `knowledge_refs`, `tool_status` | Actual run-scoped provenance/status, to be filled by the program. `EvidenceRef` has ID and log/metric/deployment type; `KnowledgeRef` has existing `document_id`, `chunk_id`, `source_ref`. |
| `degraded`, `requires_approval`, `clarification_required`, `clarification_question` | Derived control fields. A clarification question replaces a proposed production action. |

`ConfirmedFinding(statement, evidence_ids)` requires at least one operational
Evidence ID. `Hypothesis(statement, evidence_ids, verification_steps)` allows
zero citations but needs a verification step. `RecommendedAction(action, reason,
risk_level, requires_approval, related_evidence_ids)` uses low/medium/high risk;
high risk requires approval. `EvidenceGap(description, why_needed)` records
what is missing and why it matters.

V1 omits `root_cause`, `severity`, numeric diagnosis confidence, and
`support_level`. Current simulated incidents, routing scores, and Judge scores
cannot calibrate a probability that a root cause is true. A future support
level needs explicit, testable evidence criteria before it becomes a field.

## Validation boundary

`app/core/diagnosis_validation.py` is a pure validator. Its
`DiagnosisValidationContext` contains the actual mode, intent, primary and
supporting Agents, known Agents, allowed services, environment, operational
Evidence ID-to-type map, retrieved Knowledge references, Tool states,
clarification state, and any other upstream degradation flag. It performs no
Tool, RAG, database, or LLM calls.

The validator requires the structured mode/intent/routing/environment/Tool
states to match the observed run. The top-level Evidence list must exactly
match this run's Evidence IDs and types; Knowledge references must exactly
match this run's `(document_id, chunk_id, source_ref)` set. Finding, hypothesis,
and action citations must be unique and refer to those operational Evidence
IDs. Services must be in the allowed set. Duplicate service, Agent, or source
references are rejected.

`requires_approval` means **at least one recommended action requires human
approval**, and is true if and only if such an action exists. High-risk actions
must carry that flag. A conservative lexical guard also treats explicit
rollback, restart, scaling, rate-limiting, destructive SQL, and production
configuration changes as high risk. This guard is not a complete semantic
risk classifier; Stage 4-2 must derive risk from policy rather than trust a
model-supplied low-risk label.

`degraded` must equal either (a) a Tool in `failed`/`degraded` state or (b)
another explicitly observed upstream degradation. `empty` is not failure and
does not by itself set `degraded`. Failed/degraded Tool output cannot become
an Evidence citation because only validated items from the current bundle
enter the allowed map.

Clarification requires a nonempty question, no Agent result, findings,
hypotheses, production actions, Tool state, or source references. A request
such as “please provide service_name” lives in `clarification_question`, not
`recommended_actions`. Runbook mode may have Knowledge references without
operational Evidence; it cannot assert a confirmed incident finding.

**Valid references are not proof that the prose is semantically supported by
those sources.** Stage 4-1 checks identity, provenance, and control-field
consistency only. It cannot reliably detect every invented service/version
mentioned inside arbitrary free text or establish causal entailment. Later
Evaluation, Judge review, and human review remain necessary.

## Failure status and examples

`DiagnosisBuildResult` separates `not_run`, `success`, `validation_failed`,
`parse_failed`, and `assembler_failed`. Only `success` may contain an
`IncidentDiagnosis`; any failure must contain an error code and no diagnosis.
When Assembler is introduced later, the existing Markdown `response` must
remain available if structured construction fails. This batch does not call
an Assembler or change `/chat`.

- Normal INC-001 fixture: Application primary, Database supporting, full
  `L001/M003/D001` IDs, a pool-saturation finding citing L001/M003, release
  as a hypothesis citing D001, and rollback *evaluation* marked high-risk and
  approval-required. The release is not a confirmed root cause.
- Runbook-only fixture: `status=runbook`, DB Runbook document/chunk/source
  reference, no operational Evidence or confirmed incident finding, low-risk
  general inspection steps.
- Clarification fixture: `status=clarification`, empty findings/hypotheses/
  actions, `clarification_required=true`, and a specific service-name question.

Deterministic fixtures and negative cases live in
`app/test_rootlens_incident_diagnosis.py`. Stage 3's approved baseline remains
untouched; no paid Judge rerun is needed because the runtime path is unchanged.

## Stage 4-1 acceptance

The new contract has 32 deterministic tests covering the normal INC-001
fixture, unknown/duplicate citations, service and Agent mismatches, approval
consistency, clarification, runbook-only mode, empty versus failed/degraded
Tool states, schema/version rejection, and fail-closed build status. The full
Stage 1/2/3 plus Stage 4-1 suite passed **217/217** in an isolated container
with disposable Redis. Neither the live app nor the approved baseline was
rebuilt or changed. Stage 4-2 may begin after review, but must first preserve
actual per-Agent execution results before an Assembler attempts multi-Agent
structure. No Stage 4-2 work was performed here.
