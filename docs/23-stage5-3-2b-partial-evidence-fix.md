# Stage 5-3.2B Partial-Evidence Provenance Fix Report

Status: the data-boundary fix and offline regression passed. Live acceptance is
blocked by provider HTTP 402 `Insufficient Balance`; Stage 5 remains open.
No baseline was promoted and Stage 6 was not started.

## Scope and versioning

- Preserved `app/datasets/runtime` and `app/datasets/evaluation/stage3-v2.json`
  unchanged as the approved `rootlens-demo:v1` / `stage3-v2` reference.
- Added `app/datasets/snapshots/v2/runtime` as the new default runtime snapshot.
  Its manifest says `rootlens-demo:v2`. All source records match v1 except
  INC-004 M401's summary: before, `Shipping HTTP 5xx rate reached 12 percent;
  log source has no records`; after, `Shipping HTTP 5xx rate reached 12 percent`.
  The metric attributes, service, environment and timestamps are unchanged.
- Added `app/datasets/evaluation/stage3-v3.json`. Only expected Evidence IDs
  changed from `rootlens-demo:v1:*` to `rootlens-demo:v2:*`; inputs and semantic
  labels are unchanged. The new suite fingerprint is
  `cfd88d288be27cf0a106c8f2bd14c5154ae030bf7c0569f6300ad5d019334d70`.
- `IncidentTools` now defaults to the v2 snapshot; the v1 root remains
  explicitly available as `LEGACY_RUNTIME_ROOT`. The API reads the manifest
  version and Docker mounts the v3 evaluation suite. DiagnosisAssembler,
  Validator, Agent prompts, Router, RAG, Judge and public schemas were not
  changed.

## Tests and deployment

Four deterministic tests were added: v1/v2 fixture diff, INC-004 evidence
and tool-state separation, v2/v3 suite label equivalence, and an offline
INC-004 structured/Trace check. Existing version-dependent tests were updated.
The complete isolated offline run passed: **286 passed, 0 skipped, 0 failed**.
The disposable Redis test service was stopped afterward. These tests establish
input provenance and contract behavior; they do not make the Validator a
semantic-entailment checker or prove a live model can never miscite a source.

`docker compose config --quiet` passed. Only `rootlens-app` was rebuilt; it
became healthy and `GET /health` returned `ok`. No API key was printed.

## Live acceptance stopped

The first fresh INC-004 `POST /chat` returned HTTP 200 with intent
`service_incident`, Application primary, `query_logs=empty`,
`query_metrics=ok`, `query_deployments=empty`, and only the v2 M401 Evidence
ID. However, `diagnosis_status=assembler_failed` and no structured diagnosis
was returned. App logs show provider HTTP 402 `Insufficient Balance` during
Intent, RAG rewrite/rerank, Agent execution and Assembler calls. Therefore
this result cannot assess the provenance fix's live stability. As required,
the remaining two INC-004 calls and the six-case judged/structured evaluation
were not attempted. No automatic Prompt or dataset tuning followed.

The old approved baseline ID remains
`9bd1b2a57d5b411f87541bdcba521af4` (`stage3-v2`,
`rootlens-demo:v1`). A metadata-only call to the existing comparator for the
v3/v2 suite returned `incompatible` with reasons `suite_version`,
`dataset_version`, `suite_fingerprint`. No delta was calculated, and the old
snapshot/pointer was not changed. The new run is **not** a baseline candidate
yet. Stage 3 real metrics, Judge v2, Stage 4 structured metrics and Stage 5
live Trace/reliability regression were not run in this blocked acceptance.

## Next acceptance gate

After the configured provider balance is restored, restart `rootlens-app` to
clear transient monitor penalties from the failed calls. Then run three
independent INC-004 live requests and inspect every confirmed finding: M401
may support the 12% 5xx metric, while empty logs/deployments remain tool
states or gaps and `degraded=false` unless another failure occurs. Stop on
any cross-source citation. Only after 3/3 clean, run the new six-case suite
with Judge and structured output, inspect normal operational citations,
Runbook and clarification, and perform Stage 5 Trace/reliability regression.
The old baseline should remain incompatible by design; any new baseline
promotion and formal Stage 5 closure require separate owner approval.
