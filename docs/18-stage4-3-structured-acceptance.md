# Stage 4-3 Structured Diagnosis Acceptance

Date: 2026-10-02 (Asia/Shanghai). This is an acceptance run on the **six-case
synthetic** RootLens suite, not a production-accuracy estimate.

## Scope and compatibility

- `POST /chat` still returns the original Agent Markdown in `response`. It now
  additionally returns `diagnosis: IncidentDiagnosis | null` and
  `diagnosis_status: not_run | success | parse_failed | validation_failed |
  assembler_failed`. The full per-Agent execution records remain internal.
- `POST /eval/run` defaults to the unchanged Stage 3 path. RootLens callers may
  explicitly set `include_structured=true`; this adds a separate `structured`
  section with per-case results and Stage 4 metrics. Legacy evaluation rejects
  this option. Stage 3 observations, metric names/denominators, Judge v2 rubric,
  suite fingerprint, and baseline comparator are unchanged.
- An actual `/chat` Runbook request returned HTTP 200, a 1007-character Markdown
  `response`, `diagnosis_status=success`, a valid `status=runbook` diagnosis,
  knowledge IDs, and no operational evidence. An old client reading only
  `response` remains compatible. A failed build returns `diagnosis=null` while
  the same Agent response remains available.
- `DiagnosisBuildResult` has optional Assembler latency and provider-reported
  token counters. These are build metadata, **not** changes to
  `IncidentDiagnosis v1`.

## Environment and baseline

`docker compose config --quiet` passed. Only `rootlens-app` was rebuilt; the
RootLens app, Redis, ChromaDB, Nginx, and Prometheus reported healthy. The
approved baseline ID is `9bd1b2a57d5b411f87541bdcba521af4`; SHA-256 of
`app/data/eval/rootlens/approved.json` was unchanged at
`3B88F01ED03340416289D8D062C82901D31151F588B1C8908D33B8E5567C8880`.
No baseline promotion or dataset/label change occurred.

Real run: `rootlens-diagnosis:stage3-v2`, `rootlens-demo:v1`, evaluation schema
`1`, Judge schema `2`, `IncidentDiagnosis` schema `1`, provider
`api.deepseek.com`, model `deepseek-v4-flash`. Request:
`POST /eval/run {"include_judge":true,"include_structured":true}`.

## Six-case review

| Case | Structured result | Human review |
| --- | --- | --- |
| INC-001 | success; Application primary, Database supporting | Pool at limit and connection timeouts cited from M003/L001; 5xx and payment HTTP 500 cited from M002/L002. v2.3.7 relationship remains a hypothesis. Rate limit and rollback suggestions require approval. |
| INC-002 | success; Application only | L201/M201 support application validation failure and 18% 5xx. Extra DB/DEP Runbook hits did not become confirmed database findings or supporting routing. |
| INC-003 | success; Infrastructure | CPU saturation cites L301/M301. The older incident is not presented as current operational evidence. |
| runbook-db-pool | success; runbook | No operational evidence or confirmed incident findings; knowledge references come from this run's retrieval. |
| clarify-missing-service | success; clarification | No Assembler model call, question is nonempty, findings/hypotheses/actions empty. |
| INC-004-partial | success; Application | Only the M401 12% 5xx measurement is a confirmed finding. Log and deployment tools are `empty`, not `failed`; root cause remains open and `degraded=false`. |

The first live attempt built only 2/6: three responses hit the Assembler's
1800-token output limit and one was rejected by validation. Only the new
Assembler's output budget, concise synthesis instruction, and safe validation
logging were adjusted; Router, Intent, RAG, Evidence, Agent prompts, Judge,
datasets, and baseline were not changed. A later human review caught a
source-attribution issue in INC-004, so the Assembler prompt was tightened to
keep tool states outside cited confirmed findings. A targeted real retest
confirmed that M401 is cited only for the 12% 5xx observation. The final full
six-case run reported **6/6 successful structured builds**.

## Stage 4 metrics

Stage 4 metrics live under `structured.metrics`, never in the Stage 3 `metrics`
map or baseline comparator. Each metric reports numerator, denominator, and
value/null. In the final six-case run:

| Metric | Result | Denominator meaning |
| --- | --- | --- |
| diagnosis_build_success_rate | 6/6 | RootLens cases with structured evaluation enabled |
| structured_schema_valid_rate | 6/6 | Successful builds |
| invalid_evidence_ref_count | 0 | Six cases; accepted diagnoses only |
| invalid_knowledge_ref_count | 0 | Six cases; accepted diagnoses only |
| confirmed_finding_source_coverage | 8/8 | Confirmed findings in accepted diagnoses |
| approval_policy_accuracy | 15/15 | Actions in accepted diagnoses |
| approval_policy_violation_count | 0 | Six cases; accepted diagnoses only |
| clarification_structure_accuracy | 1/1 | Observed clarification cases |
| degraded_flag_accuracy | 6/6 | Accepted diagnoses with comparable upstream state |

Rejected or unparseable model output has `diagnosis=null` and is captured by
build status/rate, not by a fabricated reference count. Because the validator
requires valid IDs and approval labels before a diagnosis can be accepted,
the corresponding 100% metrics demonstrate contract compliance **only**. They
do not measure whether prose is semantically entailed by the cited source,
whether a root cause is correct, or whether an omitted action was necessary.

Offline controlled tests cover malformed JSON, unknown Evidence/Knowledge
IDs, mislabeled high-risk actions, Agent fallback and supporting failure,
Tool failed/degraded versus empty, preserved Markdown, default evaluation
opt-out, and failure observations. The full offline regression suite passed
**242 tests**.

## Judge, regression, and cost

The existing Judge v2 still scored only the natural-language Agent response:
6 valid / 0 failed, coverage 1.0, overall mean 0.9146. No structured semantic
Judge was added. Stage 3 approved baseline was read successfully,
`compatible=true`, `regression.status=compared`; all six configured
deterministic comparison deltas were zero and all Judge deltas were `stable`
(overall delta -0.0021). These are regression results on the same synthetic
suite, not a claim of general diagnostic accuracy.

The final run made five Assembler model calls and skipped clarification.
Measured Assembler latency ranged from 2.81 to 5.01 seconds, mean 3.58 seconds.
The provider reported 12,458 input and 4,591 output tokens across those five
calls. This is additional latency and token consumption beyond the Stage 3
Agent/Judge calls; no currency cost is inferred without verified pricing.

## Remaining limits

The six cases are synthetic and internally consistent, not a production
sample. RootLens RAG still has known extra-hit noise. Source-ID validation is
not semantic entailment; the human source-attribution correction above shows
why review is necessary. Judge v2 is not calibrated against a large human set.
Stage 4 added no Trace, failure-injection platform, database, or frontend.
Stage 4-3 implementation and acceptance are complete; formal Stage 4 closure
and any Stage 5 work remain a separate owner decision.
