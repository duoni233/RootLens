# Stage 5-1: Diagnosis Execution Trace v1

Status: offline implementation and deterministic regression accepted. Failure
injection, reliability metrics, full Trace API, and live Docker/LLM acceptance
belong to later Stage 5 batches. No Stage 3 baseline was changed.

## Scope and identity

`run_diagnosis` creates a request-scoped `trace_id` before Intent Recognition.
It finishes after `DiagnosisPipeline.run` and attaches the internal trace to
`DiagnosisOutcome.trace`. An Evaluation call may add its separate `eval_run_id`.
The `request_id` comes from the existing Orchestrator Request; it can be absent
for an early QueryContext clarification. None of these IDs is substituted for
another. The ordinary `/chat` and `/eval/run` response formats are unchanged.

This is a **Diagnosis execution** trace, not an HTTP end-to-end trace. `/chat`
reads Redis Memory before this scope and writes it afterward. A Trace duration
therefore cannot be reported as total HTTP request latency.

## Contract

`DiagnosisTrace` v1 contains `schema_version`, `trace_id`, optional `request_id`
and `eval_run_id`, UTC `started_at`/`completed_at`, `overall_status`, `degraded`,
and `steps`. A `TraceStep` contains `step_id`, `step_type`, `component`,
`status`, UTC `started_at`/`completed_at`, monotonic `latency_ms`, optional
`result_kind`, sanitized `error_code`, `degraded`, whitelisted `metadata`,
`evidence_ids`, and `knowledge_ids`.

Step status is `success`, `failed`, `degraded`, or `skipped`. An empty successful
tool result is `success + result_kind=empty`, not a failure. A successful result
with records is `success + result_kind=items`. A usable Markdown answer with a
failed Tool/RAG/Agent/Assembler step makes the overall status `degraded`; no
usable answer is `failed`. A clarification is normally `success`, even though
downstream diagnosis work is skipped. `skipped` is not an overall status.

## Observed steps and sources

| Step | Observation source |
| --- | --- |
| `intent_recognition` | Shared entry around `recognize_intent`; `IntentResult` supplies intent, source names, and its own latency. |
| `evidence_gate`, `query_context` | Existing Pipeline gate and `build_query_context` return. |
| `query_logs`, `query_metrics`, `query_deployments` | Separate parallel ToolManager calls, then original `EvidenceBundle` validation. Trace uses the final `ToolObservation` status and accepted Evidence IDs. |
| `rag_rewrite`, `rag_retrieval`, `rag_rerank` | Existing ToolManager stage boundaries; `KnowledgeResult.stages` supplies a status-only observation if a supplied lookup has no timed child event. |
| `routing` | One existing Orchestrator routing decision, with chosen primary/supporting Agent identities. Scores are heuristic domain relevance, not root-cause probabilities; v1 does not copy the raw reason or scores. |
| `agent_execution` | Each actual `_execute` attempt and its `AgentExecutionRecord`, including a separate GeneralOps fallback attempt. No Agent content is copied. |
| `diagnosis_assembly` | Existing `DiagnosisBuildResult` status, error code, latency and token counters where available. Clarification uses deterministic `assembler.clarify`, with `llm_called=false`. |

Tools and supporting Agents can run concurrently. Step array order is an
observation/display order, **not** proof of serial execution. Compare each
step's own timestamps to understand overlap. `timing_source=not_measured`
marks a result-only RAG stage observation; its tiny recording duration must
not be presented as actual model/retrieval latency.

For early clarification, Tools, RAG, routing, and Agent steps are marked
`skipped` when they were not executed. QueryContext may already have executed
and asked for clarification. Deterministic structured clarification can still
produce a successful `diagnosis_assembly` step without an LLM call.

## Safety and compatibility

The recorder uses a whitelist of metadata keys and fixed error codes. It does
not store prompts, Authorization headers, secrets, hidden model reasoning,
full Agent Markdown, raw exceptions, or stack traces. Evidence and knowledge
are referenced by IDs only. Recorder failures are isolated from the diagnosis
path. The normal user API does not expose this full internal trace; an access-
controlled debug view is a later decision.

Trace IDs are ready to link a future persisted DiagnosisRun, IncidentDiagnosis,
and DiagnosisTrace, but Stage 5-1 adds no database or trace retention service.
The in-memory trace lives only as long as the returned outcome is retained.

## Offline acceptance and limits

The 15 new tests cover normal and parallel execution, empty/failed/degraded
Tools, fallback attempts, supporting failure, parse failure with preserved
Markdown, clarification, real RAG stage observations, ID links, timing,
metadata filtering, and recorder failure isolation. Full offline regression:
**254 passed, 3 skipped** in a disposable container using E-drive wheels and
a read-only source mount. No live app was rebuilt, no paid model was called,
and the approved baseline was not touched.

Known v1 gaps: this is not Redis/API tracing; routing has no separate score
snapshot; RAG outer exception paths can fall back to status-only observations;
trace objects are not persisted or queryable over HTTP. Controlled failure
injection and reliability metrics remain Stage 5-2 work.
