# Stage 3-4.1B Targeted Quality Fix Report

## Scope and changes

This batch adjudicates Intent taxonomy, filters RootLens entities at the shared
runtime entry, and makes the existing four-dimension Judge aware of the *observed*
diagnosis/runbook/clarification mode. It does not tune Router thresholds, RAG,
Evidence Tools, Memory, or baseline thresholds.

| File | Change |
| --- | --- |
| `app/core/intent_recognizer.py` | Clarified release-focus taxonomy in comments and LLM instructions; generic pattern boundary checks for release-focused requests. |
| `app/core/rootlens_config.py` | Explicit six-field entity projection, empty-value removal, and rejection of values overlapping legacy order/product/amount entities. |
| `app/core/diagnosis_entry.py` | Applied projection before the shared `/chat` and evaluation DiagnosisPipeline entry; legacy extraction remains intact. |
| `app/evaluation/rootlens_judge.py`, `app/evaluation/rootlens_evaluator.py` | Observed-mode Judge guidance with unchanged four-score output schema. |
| `app/evaluation/rootlens_baseline.py`, `app/evaluation/rootlens_cases.py`, `app/docker-compose.yml` | Suite v2, Judge schema v2, and read-only v2 case mount. |
| `app/datasets/evaluation/stage3-v2.json` | Copied the six-case suite, changing only INC-001 expected Intent. The v1 file remains historical. |
| `docs/01-rootlens-target-map.md` | Documented the final taxonomy boundary and current entity projection. |
| `app/test_rootlens_quality_fix.py`, `app/test_rootlens_first_slice.py`, `app/test_rootlens_evaluation_integration.py`, `app/test_rootlens_judge_baseline.py` | 15 new collected deterministic cases plus updates to existing assertions. |

## Taxonomy and data boundary

- `service_incident`: primarily investigating the service symptom; no clear request to investigate a specific change. “Not sure whether a release is related” remains here.
- `deployment_issue`: explicitly investigating the relationship between a recent release, version, or configuration change and the anomaly. Classification does **not** establish causation.
- Cross-boundary messages A-E from the adjudication pass deterministic pattern tests. No case ID or provider-specific output is hardcoded. INC-001 is labeled `deployment_issue` in v2.
- RootLens allows only `date`, `service_name`, `start_time`, `version`, `status_code`, `error_code` into its pipeline, Agent request/context, Router, and API entity output. Empty values and values duplicated in legacy `order_id`, `product`, or `amount` are dropped. This catches an actual legacy overlap where order ID `AB1234` was also extracted as `error_code`.
- The shared recognizer still extracts old customer-service entities; the legacy route can still consume them. Filtering is limited to the RootLens shared entry.

Version/fingerprint: `stage3-v1` / `14013e52d1deac47b2d5f27952af4c618ed6f9ec7e152d8033242c88779372ae` -> `stage3-v2` / `1c793c746074ac67eeafe59462b6a4aaafdb1f2431ebf6cce2b68e5afc87fe68`. Evaluation schema stays `1`; Judge schema changes `1` -> `2`. A v1 Judge baseline/report cannot be compared as a compatible v2 regression.

## Judge v2

The four fields remain `evidence_grounding`, `diagnostic_reasoning`, `actionability`, and `safety_and_uncertainty`. Mode is selected from the actual observation, never the expected label. In `clarification`, reasoning means recognizing insufficient context and stopping diagnosis; actionability means asking for the minimum specific missing information. It is not penalized for omitting root-cause guesses, Tool/RAG calls, or full troubleshooting steps; a vague request remains weak. `runbook` does not require operational evidence and must distinguish general knowledge from incident facts. `diagnosis` retains the prior evidence-based semantics. Tests check dispatch, guidance, and v1/v2 baseline incompatibility; the model's numeric judgment is validated by the real run below.

## Verification

- Compose config valid; `rootlens-app`, ChromaDB, Redis, Nginx, Prometheus healthy after rebuilding only the app. HTTP `POST /eval/run` returned 200.
- Model/provider: `deepseek-v4-flash` / `api.deepseek.com`; runtime dataset `rootlens-demo:v1`; six-case `stage3-v2` suite; evaluation schema `1`; Judge schema `2`. No secret is recorded.
- Full deterministic regression: **185 passed**. Temporary test Redis and network were removed.
- Judge attempted/valid/failed: **6/6/0**; coverage **1.0**; status `complete`. No approved RootLens baseline exists, so `regression.status=no_baseline`.

| Case | Intent | Primary / supporting | Evidence | Tools (logs / metrics / deployments) | Runbook IDs | Clarification | Judge v2 overall |
| --- | --- | --- | ---: | --- | --- | --- | ---: |
| INC-001 | deployment_issue | application / database | 9 | ok / ok / ok | DB, APP, DEP | no | 0.9375 |
| INC-002 | service_incident | application / none | 2 | ok / ok / empty | APP, DEP, DB | no | 0.9250 |
| INC-003 | resource_issue | infrastructure / none | 2 | ok / ok / empty | APP, DEP | no | 0.9250 |
| runbook-db-pool | runbook_query | database / none | 0 | not called | DB, APP | no | 0.9125 |
| clarify-missing-service | service_incident | none | 0 | not called | none | yes | 0.8750 |
| INC-004-partial | service_incident | application / none | 1 | empty / ok / empty | APP, DEP, DB | no | 0.9250 |

All six Judge responses were valid. Per-dimension means over valid cases: evidence grounding **0.9417**, diagnostic reasoning **0.9083**, actionability **0.8750**, safety/uncertainty **0.9417**; overall mean **0.9167**. Deterministic metrics: Intent Accuracy **6/6**, Macro-F1 **4/4 class sum = 1.0**, primary accuracy **4/4**, supporting exact **4/4**, supporting partial **4/4**, required Evidence coverage **9/9**, Tool status **6/6**, clarification **6/6**, Runbook hit **3/3**, forbidden-claim violations **0/2 applicable cases**. These denominators are small and not a production-quality claim.

## Human review and comparison with Stage 3-4

- INC-001: the actual Intent was already `deployment_issue` in the v1 run; v2 aligns the adjudicated label. Both Agents tie pool exhaustion/5xx to cited operational evidence while calling the release only a time-correlated, unproven cause. The response does not execute rollback or pool changes.
- Runbook: the response and tested Agent context contain no `order_id`, `amount`, or `product`. It asks for missing incident details and presents Runbook steps as general guidance, not observed incident facts. It references an older incident only as a comparison, not as this event's cause.
- Clarification: asks only for the affected service name. No Tool, RAG, or Agent diagnosis ran. Judge v2 gave 0.875 versus v1's 0.725, but these scores have different rubrics and are **not a compatible regression comparison**.
- INC-002 remains application-only; INC-003 remains infrastructure; INC-004 correctly discloses one metric and two empty Tool results. Other routing, required Evidence, Tool status, clarification, and Runbook hit metrics did not regress.
- Known retrieval noise remains: INC-002 and INC-004 still include DB and DEP Runbooks despite no corresponding operational evidence. The responses label such paths as hypotheses and do not claim DB or deployment as confirmed cause. This is a follow-up quality issue, not silently fixed here.
- Old Stage 3-4 deterministic Intent Accuracy was **5/6**, now **6/6** due to the adjudicated expected label and consistent recognition. Judge v1 overall mean was **0.8896**, Judge v2 **0.9167**; do not interpret the difference as a measured model improvement because scoring semantics changed. The original v1 report is untouched.

## Decision

No blocking defect was found in this six-case targeted acceptance. The suite is tiny, uses internally consistent simulated incidents, and retains extra RAG hits; these limitations must accompany any resume or interview claim. The new result is a reasonable **candidate** for the first approved RootLens baseline after human review, but no promotion was performed. Keep Stage 3 formally open until the owner reviews the [raw six-case report](14-stage3-4.1b-evaluation-raw.json) and explicitly approves baseline promotion/closure. Do not enter Stage 4 automatically.
