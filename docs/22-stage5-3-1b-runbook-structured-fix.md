# Stage 5-3.1B: Runbook Structured Diagnosis Fix

Status: **runbook blocker resolved; Stage 5 closure not yet recommended**.
Real-model runbook acceptance passed 3/3 and the six-case structured evaluation
passed 6/6. A separate human review of a fresh partial-evidence `/chat` found
a source-attribution defect outside this runbook-only change. No automatic
Stage 6 work or baseline promotion occurred.

Date: 2026-10-04 (Asia/Shanghai). All evaluation cases are synthetic.

## Scope and contract

Only `app/core/diagnosis_assembler.py` changed in runtime code. Diagnosis mode
retains its original synthesis prompt and payload. Clarification remains
deterministic. Runbook mode now has a separate strict internal payload:

- The model returns only `summary`, `recommended_actions`, and
  `evidence_gaps`. A runbook action returns `action`, `reason`, `risk_level`,
  and `requires_approval`. Both internal models reject extra fields.
- The program owns `confirmed_findings=[]`, `hypotheses=[]`, and every
  `recommended_action.related_evidence_ids=[]`. It continues to populate
  `evidence_refs`, `knowledge_refs`, Agent identities, service, intent, Tool
  status, and degradation from the observed run.
- A model response containing `confirmed_findings`, `hypotheses`,
  `evidence_ids`, nested `related_evidence_ids`, or other forbidden fields
  fails closed. The Assembler does not silently strip invalid citations.
- The original run-scoped Validator and public `IncidentDiagnosis v1` were
  **not changed**. Knowledge chunk IDs are still not operational Evidence IDs.

This is an internal mode-specific generation contract, not a new public
diagnosis schema. High-risk action approval checks and the original Agent
Markdown response are preserved.

## Deterministic and live verification

`app/test_rootlens_stage4_assembler.py` gained runbook and diagnosis boundary
tests; one existing Stage 5 runbook Trace fixture in
`app/test_rootlens_stage5_trace.py` now uses the new runbook-only model output.
The tests cover program-owned empty citations, current Knowledge references,
rejection of Runbook and historical chunk IDs in Evidence fields, strict
extra-field failure, high-risk approval, ordinary diagnosis citations, and
Trace behavior. Existing Validator and clarification tests remained active.
Nine test cases were added; targeted Assembler/contract/Trace regression was
72/72. Full Stage 1-5 regression with a temporary isolated Redis was
**282 passed, 0 skipped, 0 failed**. The Redis test container was removed.

Only `rootlens-app` was rebuilt; app, Redis, ChromaDB, Nginx, and Prometheus
were healthy after testing. Three consecutive real HTTP `/chat` Runbook
requests all returned `runbook_query`, `diagnosis_status=success`,
`IncidentDiagnosis.schema_version=1`, and `status=runbook`. In all three:
`evidence_refs=[]`, `confirmed_findings=[]`, `hypotheses=[]`, all three actions
had empty `related_evidence_ids`, `knowledge_refs` had three current sources,
and operational `tool_status={}`. RAG rewrite/retrieval/rerank were performed.
These three successes are a small stability smoke test, not a statistical
reliability claim.

The subsequent real `POST /eval/run` with both `include_judge=true` and
`include_structured=true` used the unchanged six-case `stage3-v2` suite and
fingerprint `1c793c746074ac67eeafe59462b6a4aaafdb1f2431ebf6cce2b68e5afc87fe68`.
Structured builds were **6/6**, schema validity 6/6, accepted invalid
Evidence/Knowledge reference counts both 0, cited finding coverage 8/8,
approval policy 15/15, clarification structure 1/1, and degraded-flag match
6/6. The runbook case had no operational Evidence/finding/hypothesis or
action Evidence citation and retained its actual Knowledge references. Normal
diagnosis cases retained their operational citations; clarification and
partial-evidence cases retained their expected structured states.

Stage 3 approved baseline ID
`9bd1b2a57d5b411f87541bdcba521af4` remained readable and compatible;
`regression.status=compared`. All six configured deterministic comparisons
had zero delta and stable status. Judge v2: 6 valid, 0 invalid, coverage 1.0,
overall mean 0.9217. All Judge comparison statuses were stable. The approved
baseline file SHA-256 remained
`3B88F01ED03340416289D8D062C82901D31151F588B1C8908D33B8E5567C8880`.
IncidentDiagnosis schema `1`, evaluation schema `1`, Judge schema `2`, suite
version/fingerprint, runtime dataset, and baseline were unchanged. Stage 5
Trace and controlled failure implementation were not modified; their offline
regressions are included in the 282 passing tests.

## Human review and closure decision

A separate fresh HTTP check of INC-001 yielded supported operational findings,
Application primary and Database supporting, and kept deployment-related
causes as hypotheses. A fresh INC-004 partial-evidence check, however,
returned a second `confirmed_finding`: "the metric source also shows no log
records", cited to M401. M401's synthetic metric summary itself contains
the cross-source phrase `log source has no records`, but the Stage 4 provenance
rule explicitly keeps `query_logs=empty` as a Tool state outside a finding
cited to a metric ID. The prior Stage 4-3 review had only the 12% 5xx metric
as a confirmed finding. The six-case evaluation in this batch produced a
valid INC-004 object; this extra HTTP call demonstrates model-output
variability that schema and ID-validity metrics do not catch.

This is **not evidence that the runbook-only code change caused an ordinary
diagnosis regression**: the diagnosis prompt and synthesis branch are
unchanged. It is also not acceptable to call the broader human-review gate
fully clean. This batch does not modify the runtime dataset, diagnosis prompt,
Validator, or Stage 4 metrics to hide the observation. The runbook blocker is
closed, but formal Stage 5 closure should await an explicitly scoped review
of this partial-evidence source-attribution issue and owner acceptance. Do
not enter Stage 6 automatically.
