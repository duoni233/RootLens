# RootLens Stage 3 Closure

Status: **completed**, 2026-10-01. This closes the Evaluation stage only; Stage 4 has not started. No business code was changed during closure.

## Approved baseline

The owner explicitly approved the [Stage 3-4.1B real six-case report](14-stage3-4.1b-evaluation-raw.json). It was promoted once with the existing `python -m evaluation.rootlens_baseline promote` CLI. Ordinary `/eval/run` did not promote anything.

| Field | Approved value |
| --- | --- |
| baseline_id | `9bd1b2a57d5b411f87541bdcba521af4` |
| approved pointer | `E:\code\RootLens\app\data\eval\rootlens\approved.json` |
| history snapshot | `E:\code\RootLens\app\data\eval\rootlens\history\9bd1b2a57d5b411f87541bdcba521af4.json` |
| suite | `rootlens-diagnosis:stage3-v2` |
| dataset | `rootlens-demo:v1` |
| evaluation / Judge schema | `1` / `2` |
| model / provider | `deepseek-v4-flash` / `api.deepseek.com` |
| case IDs | `INC-001`, `INC-002`, `INC-003`, `INC-004-partial`, `clarify-missing-service`, `runbook-db-pool` |
| suite fingerprint | `1c793c746074ac67eeafe59462b6a4aaafdb1f2431ebf6cce2b68e5afc87fe68` |

Approved deterministic metrics: Intent Accuracy 6/6, Macro-F1 1.0 (4 applicable classes), primary Agent 4/4, supporting exact and partial 4/4 each, required Evidence 9/9, Tool status 6/6, clarification 6/6, Runbook hit 3/3, forbidden-claim violations 0/2 applicable cases. Judge v2: 6 valid, 0 failed, coverage 1.0; evidence grounding 0.9417, diagnostic reasoning 0.9083, actionability 0.8750, safety/uncertainty 0.9417, overall 0.9167.

Approved pointer and history snapshot matched the approved report's metrics and shared the SHA-256 `3B88F01ED03340416289D8D062C82901D31151F588B1C8908D33B8E5567C8880` immediately after promotion and after the verification run. One history JSON exists. Its content was not overwritten.

## Post-promotion regression

The first post-promotion HTTP evaluation returned `invalid_baseline` because the one-shot root CLI wrote JSON as `root:root` with mode `600`; the running application uses uid 1000. This [diagnostic response](15-stage3-closure-regression-raw.json) is retained. File read permissions alone were changed to `644` on the pointer and matching history snapshot; content hashes stayed unchanged. The non-root app then loaded the approved ID successfully.

A second identical six-case real evaluation returned HTTP 200 and is saved as the [verified regression response](15-stage3-closure-regression-verified.json):

- `baseline_id=9bd1b2a57d5b411f87541bdcba521af4`, `compatible=true`, `regression.status=compared`, `model_changed=false`.
- All six deterministic metrics included by the existing regression comparator are `stable`, delta `0.0`.
- Judge v2: 6/6 valid, coverage 1.0; all comparator fields are `stable`. Diagnostic reasoning mean delta `+0.00333`; overall mean delta `+0.00083`; other Judge deltas `0.0`. These small changes are normal across real model calls and do not indicate a schema mismatch.
- The comparator currently checks six selected deterministic metrics, not every metric stored in the baseline. The remaining stored metrics should not be described as having computed regression deltas.

## Scope and limits

This is a **six-case synthetic regression suite** built from internally consistent simulated incidents, not production data and not an estimate of production diagnostic accuracy. Known RAG extra-hit noise remains in some cases. Judge v2's mode-aware rubric has not been calibrated against a large human-labeled set. V1 Judge scores are not directly comparable with v2. The baseline records the first approved local reference point, not a claim of general reliability.

Operational note: the current promote CLI creates owner-only temp files. When promoting from a root container, the non-root app needs explicit read permission on newly written approved JSON. Future promotions should account for this deployment permission boundary; no CLI or business code was changed in this closure.
