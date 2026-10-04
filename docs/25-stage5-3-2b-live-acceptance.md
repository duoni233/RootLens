# Stage 5-3.2B Live Acceptance (v2 Evidence Provenance)

Date: 2026-10-04. The earlier HTTP 402 block is recorded in
`23-stage5-3-2b-partial-evidence-fix.md`; this document records the resumed
acceptance after provider balance was restored. No code, Prompt, label, Judge
rubric or baseline was changed during this acceptance.

## Runtime and INC-004 gate

`rootlens-app` was restarted to clear the prior 402-related monitor penalties,
then remained healthy. `GET /health` returned `ok`. Three fresh INC-004
`POST /chat` requests used independent conversation IDs. All **3/3** returned
`diagnosis_status=success`, `status=diagnosis`, Application primary,
`query_logs=empty`, `query_metrics=ok`, `query_deployments=empty`, and
`degraded=false`. Each had one confirmed finding: shipping-service HTTP 5xx
rate reached **12%**, cited only to `rootlens-demo:v2:INC-004:metric:M401`.
Log and deployment absence appeared in tool state/evidence gaps, not in a
M401-backed finding. RAG rewrite, retrieval and rerank each reported
`performed` in these three calls.

## Six-case live evaluation

`POST /eval/run` used `include_judge=true` and `include_structured=true`.
Two complete runs returned HTTP 200 with 6/6 structured builds and 6/6 valid
Judge results. The second run's **exact raw response** is preserved in
`24-stage5-3-2b-evaluation-raw.json` (SHA-256
`BD69B0F1B37A30FE0BE260677D1B41F0540E5B5DA1EC0D33D3CD23CCCB433F59`).
The first run's raw save was denied by workspace permissions; its compact
terminal result showed Judge overall 0.9196. The preserved second run is the
sole report considered below; Judge overall was 0.9167. No result was
silently overwritten.

| Case | Observed route | Structured finding review | Judge overall |
| --- | --- | --- | ---: |
| INC-001 | deployment_issue; Application + Database | M001/M002 support 5xx rise; M003/L001/L002 support pool saturation and 500; deployment is a hypothesis, not confirmed root cause | 0.9375 |
| INC-002 | service_incident; Application | L201/M201 support checkout validation error and 18% 5xx; extra DB/DEP Runbook hits do not become DB findings or routing | 0.9250 |
| INC-003 | resource_issue; Infrastructure | L301/M301 support CPU saturation and latency; historical incident remains guidance, not present evidence | 0.9250 |
| runbook-db-pool | runbook_query; Database | No operational Evidence, findings or hypotheses; knowledge is not treated as this incident's facts | 0.9125 |
| clarify-missing-service | service_incident; no Agent | Stops to request service name; no tools or diagnosis findings | 0.8750 |
| INC-004-partial | service_incident; Application | M401 supports only the 12% 5xx observation; logs/deployments remain empty tool states and gaps | 0.9250 |

The preserved run used `stage3-v3`, `rootlens-demo:v2`, evaluation schema 1,
Judge schema 2, `deepseek-v4-flash` through `api.deepseek.com`. Suite fingerprint:
`cfd88d288be27cf0a106c8f2bd14c5154ae030bf7c0569f6300ad5d019334d70`.

Stage 3 deterministic metrics: intent accuracy **6/6**, macro-F1 **4/4**,
primary accuracy **4/4**, supporting exact/partial **4/4**, required Evidence
coverage **9/9**, tool status **6/6**, clarification **6/6**, Runbook hit
**3/3**, forbidden-claim violations **0/2**. These are six synthetic cases,
not production accuracy estimates.

Judge v2: **6 valid, 0 failed**, coverage 1.0. Mean evidence grounding
0.9417, diagnostic reasoning 0.9083, actionability 0.8750, safety and
uncertainty 0.9417; overall mean **0.9167**. Only valid cases contribute to
these means. The Judge is not calibrated against a large human set.

Stage 4 structure: build and schema validity **6/6**; invalid Evidence and
Knowledge refs **0**; cited finding coverage **8/8**; approval policy
**15/15**, violations **0**; clarification structure **1/1**; degraded flag
**6/6**. Source-ID coverage is not a semantic-entailment metric, so the
case-by-case review above remains necessary.

## Trace, reliability and baseline

The unchanged Stage 1-5 offline suite passed **286/286**, with 0 skipped and
0 failed, before the live run. Stage 5 Trace, controlled failure injection
and reliability tests were rerun afterward: **32/32 passed**. The prior
Stage 5-3 report documented live Trace observations; this batch did not add a
Trace API or claim a new full live injection run. The app remained healthy
after evaluation.

The approved baseline remains ID
`9bd1b2a57d5b411f87541bdcba521af4`, `stage3-v2`,
`rootlens-demo:v1`. Its file SHA-256 is unchanged:
`3B88F01ED03340416289D8D062C82901D31151F588B1C8908D33B8E5567C8880`.
The v3/v2 evaluation correctly returned `compatible=false`,
`regression.status=incompatible`, with reasons `suite_version`,
`dataset_version`, `suite_fingerprint`; no delta was computed. This is a
version boundary, not a measured quality regression. No baseline was promoted.

## Human-review limits and decision

No blocking provenance defect was observed in the three targeted calls or
the six-case structured run. Known non-blocking quality caveats remain:
extra RAG Runbook hits; INC-004 natural-language Agent text briefly calls
12% a significant deviation while also correctly requesting a baseline;
and an INC-002 log's "no database error observed" can be phrased too broadly
outside that one observed request. The structured confirmed findings kept
the required source boundary. These points are retained for later quality
work, not automatically tuned during acceptance.

The v2/v3 raw report is a **candidate** for a new approved baseline after
owner review. Stage 5 is technically ready for a closure decision, but is
**not formally closed** here. Do not promote a baseline or enter Stage 6
without separate owner approval.
