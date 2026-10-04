# Stage 5 Final Closure Report

Date: 2026-10-04. Status: **COMPLETED** after Owner review of the saved
Stage 5 Final Acceptance result. This closure did not rerun the model, Judge,
or evaluation suite and did not modify business code or evaluation labels.

## Approved baseline

The existing `evaluation.rootlens_baseline` CLI explicitly promoted the exact
six-case raw report in `24-stage5-3-2b-evaluation-raw.json` (SHA-256
`BD69B0F1B37A30FE0BE260677D1B41F0540E5B5DA1EC0D33D3CD23CCCB433F59`).

| Field | Value |
| --- | --- |
| New baseline ID | `f79e1d913c7146088805290f7e1580e3` |
| Suite | `rootlens-diagnosis`, `stage3-v3` |
| Dataset | `rootlens-demo:v2` |
| Suite fingerprint | `cfd88d288be27cf0a106c8f2bd14c5154ae030bf7c0569f6300ad5d019334d70` |
| Model / provider | `deepseek-v4-flash` / `api.deepseek.com` |
| Evaluation / Judge schema | `1` / `2` |
| Judge | enabled, 6 valid, 0 failed |
| Created at (UTC) | `2026-10-04T03:29:39.710167Z` |
| Approved pointer | `app/data/eval/rootlens/approved.json` |
| Immutable history snapshot | `app/data/eval/rootlens/history/f79e1d913c7146088805290f7e1580e3.json` |
| Pointer and snapshot SHA-256 | `821F49BA337447CFB6AEBDDC6AE6334C4D7475919DD13B02D32651CC6816AC1F` |

Case IDs: `INC-001`, `INC-002`, `INC-003`, `INC-004-partial`,
`clarify-missing-service`, `runbook-db-pool`. The approved record retains
the deterministic and Judge metrics of the saved report. The new pointer and
history snapshot have identical hashes. The prior approved baseline
`9bd1b2a57d5b411f87541bdcba521af4` (`stage3-v2`, `rootlens-demo:v1`)
remains in `app/data/eval/rootlens/history/`; its SHA-256 is unchanged at
`3B88F01ED03340416289D8D062C82901D31151F588B1C8908D33B8E5567C8880`.
The old snapshot was neither deleted nor rewritten.

Promotion initially failed before writing any snapshot because the image's
non-root user could not write the mounted history directory. Retrying the
same CLI with container root succeeded. The new files were made readable by
the non-root app user without changing their contents; `rootlens-app` then
read the new approved pointer successfully. `app/data/` is Git-ignored
runtime state, while the source report and this closure record are tracked.

## Compatibility and acceptance

`BaselineStore.compare` was run against the same saved report with read-only
mounts, without paid model calls. It returned `compatible=true`,
`regression.status=compared`, no incompatibility reasons, and zero delta with
`stable` status for every available deterministic and Judge comparison item.
This proves metadata and saved-report regression compatibility; it is not a
fresh model-quality measurement.

Stage 5 delivers DiagnosisTrace v1 and step instrumentation, controlled
Failure Injection, reliability scenarios and metrics, live Trace acceptance,
Runbook structured-diagnosis stability correction, partial-evidence
provenance correction, `rootlens-demo:v2`, `stage3-v3`, and the newly approved
baseline. The saved live acceptance recorded INC-004 provenance checks
**3/3 clean**, six-case structured diagnoses **6/6**, Judge v2 **6/6 valid**,
Stage 5 Trace/reliability regression **32/32 passed**, and full offline
regression **286/286 passed**. The human source-attribution review found no
blocking defect; the provider HTTP 402 balance issue was resolved before
final acceptance. See `25-stage5-3-2b-live-acceptance.md` for case-level
findings and the exact scope of the live Trace claim.

## Non-blocking limits

- Only six synthetic cases; these metrics are not production accuracy.
- Extra RAG hits remain in some cases.
- Judge v2 has not been calibrated against a large human-reviewed set.
- No production Redis, Chroma, or provider outage study or load test.
- Full Trace is not yet persisted or queryable through a history API.

These are future work, not Stage 5 blockers. Stage 6 may be planned next,
but this closure does not implement it.
