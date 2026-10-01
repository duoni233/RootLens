# Stage 4-2: Structured Diagnosis Assembly

## Scope

The existing `/chat` response remains the Agent-produced Markdown. Stage 4-2 adds
an internal `DiagnosisOutcome.diagnosis_build_result`; it does not add a public API
field or change Stage 3 evaluation metrics, Judge, or approved baseline.

## Execution Records

`AgentOrchestrator.run` preserves one `AgentExecutionRecord` per execution attempt.
The fields are `requested_agent`, `executed_agent`, `role`, `success`, `content`,
`latency_ms`, `escalated`, `degraded`, and `error`. A failed specialist followed by
General fallback yields two records under the same requested Agent. Parallel
results remain ordered by planned primary/supporting Agent, while attempts within
each Agent retain execution order. Failed attempts are not silently discarded just
because they are absent from the final Markdown. The existing Markdown selection
and `primary_agent`/`supporting_agents` routing fields are unchanged.

## Assembly Boundary

`DiagnosisAssembler` receives the completed intent, operational evidence bundle,
knowledge result, and Orchestrator result. It never calls tools, retrieves new
knowledge, or routes Agents. The program fills status, intent, service, environment,
Agent identities, all source references, tool status, clarification state, and
degradation. The model may return only summary, findings, hypotheses, actions, and
gaps in a strict `DiagnosisSynthesisPayload`. Extra fields, malformed JSON,
incomplete model output, invalid citations, and unsafe action labels fail closed.
The Stage 4-1 run-scoped validator checks the assembled contract.

Exact duplicate findings and hypotheses are removed, preserving first occurrence.
This is syntactic deduplication, not semantic conflict resolution. The prompt asks
the model to retain disagreements as hypotheses, not confirmed facts. The current
validator establishes reference identity, not whether prose is entailed by those
references. That semantic quality remains an Evaluation/human-review concern.

The LLM cannot supply top-level knowledge or evidence reference lists. An unknown
ID in a semantic citation fails validation; an attempted extra top-level ID fails
the strict payload schema. It cannot override program-owned service or Agent fields.

## Clarification, Runbook, Degradation

Clarification from either the QueryContext gate or Orchestrator is built and
validated without an LLM call. Runbook-only results may cite knowledge, but cannot
contain confirmed incident findings without operational evidence. `empty` tool
status alone is not degraded; `failed`/`degraded` tool status, RAG stage failure,
Agent failure, or fallback is degraded. A degraded supporting attempt also adds
an explicit information gap. The result does not claim a root cause from deployment
timing alone.

Assembler/API/parse/validation failures produce `DiagnosisBuildResult` with no
diagnosis and an internal error code. They never rewrite or suppress the original
Agent response. Evaluation explicitly skips this extra assembly call in Stage 4-2,
so existing six-case Stage 3 reports retain their execution behavior and cost.

## Verification and Remaining Work

Offline tests cover success, fallback, failed supporting Agent, source IDs,
dangerous actions, duplicate output, both clarification paths, runbook-only,
tool empty/failure, malformed/model failures, and evaluation opt-out. Stage 4-3
would decide API exposure and evaluation of the new structured output; it is not
part of this batch. No live paid LLM validation or baseline promotion occurs here.
