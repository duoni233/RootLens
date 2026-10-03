# Stage 5-3: Live Trace and Reliability Acceptance

Status: **acceptance incomplete; Stage 5 is not closed**. The real-model
six-case structured regression built 5/6 diagnoses, versus 6/6 at Stage 4-3.
The runbook case was rejected by the existing validator twice in this session.
No business behavior, prompt, router, dataset, schema, Judge, or baseline was
changed to mask this result.

Date: 2026-10-04 (Asia/Shanghai). Evidence below is from the six-case synthetic
suite and controlled tests, not a production reliability or accuracy estimate.

## Baseline and environment

- Starting Git commit: `36ce3a5619b5542142a0642fb79d53acffad5803`.
- `docker compose config --quiet` passed. `rootlens-app` was rebuilt from this
  source. RootLens app, Redis, ChromaDB, Nginx, and Prometheus were healthy
  before and after acceptance. Existing stateful volumes were not reset.
- Approved baseline ID: `9bd1b2a57d5b411f87541bdcba521af4`.
  `app/data/eval/rootlens/approved.json` SHA-256 before and after:
  `3B88F01ED03340416289D8D062C82901D31151F588B1C8908D33B8E5567C8880`.
- Suite `rootlens-diagnosis:stage3-v2`, fingerprint
  `1c793c746074ac67eeafe59462b6a4aaafdb1f2431ebf6cce2b68e5afc87fe68`,
  runtime dataset `rootlens-demo:v1`, evaluation schema `1`, Judge schema `2`,
  `IncidentDiagnosis` schema `1`, `DiagnosisTrace` schema `1`.
- Provider `api.deepseek.com`, model `deepseek-v4-flash`. No key or credential
  was printed. No baseline promotion occurred.

## Real-model Trace and HTTP behavior

The internal `app/stage5_live_trace_probe.py` invokes the same shared
`run_diagnosis` core used by `/chat` and prints only a selected safe summary.
It runs in the existing app container as a separate process; its own
Prometheus listener is disabled to avoid the port already owned by the app.
The process initializes the existing lifespan, including the idempotent
knowledge upsert. This is not a full HTTP latency measurement and does not
exercise the Redis read/write portion of `/chat`. A separate real HTTP `/chat`
request confirmed the public request and response path.

| Case | Trace ID | Core duration | Observed outcome |
| --- | --- | ---: | --- |
| INC-001 | `e40b3df8282c4a148cc3b3a59b014850` | 12,687 ms | `deployment_issue`; three tools `ok`, RAG three stages performed, Application primary and Database supporting both succeeded, structured schema v1 success, Trace success/non-degraded. |
| runbook-db-pool | `5b163f95744448aeb13ecb8d30539f9e` | 9,058 ms | Operational tools skipped; RAG and Database Agent succeeded. Assembler returned `validation_failed/run_scope_validation_failed`; Trace degraded, Markdown retained, diagnosis null. |
| clarify-missing-service | `01a3a2d2e5e3493d90442e9ea3c98ac6` | 526 ms | Tools/RAG/routing/Agent skipped; deterministic clarification assembly succeeded; Trace success/non-degraded. |
| INC-004-partial | `765c9c4bcd2d4d27963bf773dc24f044` | 10,903 ms | Logs and deployments `success + empty`, metrics `success + items`; Application and structured assembly succeeded; Trace success/non-degraded. |

In INC-001, the two Agent attempts began at 16:48:45.343 and 16:48:45.348
UTC, respectively, and their execution intervals overlapped. The Trace does
not serialize parallel execution as a false sequential chain. Representative
timings from that run: intent 1,048 ms, three tools about 8 ms each in
parallel, RAG rewrite 668 ms, retrieval 212 ms, rerank 710 ms, Agent attempts
4,361/5,242 ms in parallel, assembly 4,790 ms. These are observed component
latencies, not an instrumentation-overhead benchmark. Recorder overhead was
not measured reliably and is not reported as zero.

The public `POST /chat` INC-001-like request returned HTTP 200 with
`deployment_issue`, Application primary, Database supporting, all three tool
states `ok`, all RAG stages `performed`, and structured diagnosis schema v1
`success`. The public response still has no full Trace or trace ID. No
`/trace/{id}` registry or API was added; detailed Trace remains internal to
tests and controlled diagnostics until persistence/access policy is designed.

## Controlled failure acceptance

The existing test-only `FailureController` was exercised in a disposable
Docker test container, never through `/chat`. Focused tests for
`logs-timeout`, `supporting-exception`, `assembler-json`, and `clarification`
passed **4/4**. They verify targeted failure observation, preserved unaffected
components, safe degraded/null diagnosis behavior, and clarification's clean
early stop. The full 12-scenario report from Stage 5-2 remains separate from
the Stage 3 baseline:

| Metric | Controlled result |
| --- | ---: |
| Failure detection | 9/9 |
| Degraded flag accuracy | 12/12 |
| Fallback observed | 1/1 |
| Failure containment | 12/12 |
| Skipped-step accuracy | 8/8 |
| Invalid source refs after true injected failure | 0 across 9 scenarios |

These are deterministic synthetic scenario results, not production rates.
The three previously skipped Redis compression transaction tests ran against
a temporary, unexposed, volume-free Redis container on the Docker network;
that container was then stopped and removed. Full offline regression:
**273 passed, 0 skipped, 0 failed**.

## Stage 3 and Stage 4 regression

`POST /eval/run` with Judge v2 and structured output used the unchanged six
runtime cases. The approved baseline was read, `compatible=true`, and
`regression.status=compared`. Intent, primary/supporting routing, required
Evidence, clarification, and Runbook-hit deterministic comparisons stayed at
their approved values. Judge: 6 valid, 0 invalid, coverage 1.0. Dimension
means were grounding 0.9250, reasoning 0.9083, actionability 0.8750, safety
0.9417; overall 0.9125 versus approved 0.9167 (delta -0.0042, within the
existing 0.05 regression threshold). This Judge scores Agent prose, not the
structured diagnosis.

Stage 4 structured observations in the same real run: **5/6 builds succeeded**.
All five accepted objects were schema-valid; no invalid Evidence or Knowledge
references escaped, source coverage was 8/8, action approval policy 12/12,
clarification structure 1/1, and accepted degraded flags 5/5. The runbook
case had `diagnosis=null`, `validation_failed`, and
`run_scope_validation_failed`. The app's safe validation warning identifies
`unknown hypothesis evidence`: this runbook request had no operational
Evidence, but the model supplied an unsupported Evidence ID on a hypothesis.
The validator correctly rejected it and kept the natural-language reply.
The separate internal probe observed the same failure, so this is not counted
as a one-off pass. Stage 4-3's earlier accepted live run had built 6/6.

## Security, decision, and remaining gaps

The Trace schema only admits allowlisted metadata, IDs, statuses, safe error
codes, timings, and counts. The probe prints neither prompts nor Agent text;
an actual serialized Trace was checked against the configured API key and
sensitive field markers without printing the secret. The existing offline
test also verifies that prompt, Authorization, and Markdown content cannot
enter metadata through `finish_step`. This is a targeted check, not a general
security audit of every log sink.

Trace v1 is not persisted; ordinary `/chat` does not expose it, and no public
failure-injection API exists. External Redis/Chroma/provider outages,
circuit-breaker half-open recovery, high concurrency, and production-scale
performance remain untested. Known RAG extra-hit noise and the limited Judge
calibration remain. The six synthetic cases do not establish production
diagnostic accuracy.

**Closure decision:** Trace and controlled failure acceptance passed, as did
offline regression and Stage 3 baseline comparison. Stage 5 is **not formally
closed** because the requested Stage 4 structured six-case regression did not
match its accepted 6/6 result. The next decision is a separately scoped
quality investigation of runbook-only Assembler outputs and their validation
contract, followed by a real six-case rerun. Do not silently relax source
validation or tune prompts inside Stage 5-3. Do not enter Stage 6 yet.
