# RootLens Stage 3-3: Judge and Versioned Baseline

## Scope and current state

RootLens `/eval/run` still runs the Stage 3-2 shared Intent Recognition +
DiagnosisPipeline path. The default is deterministic evaluation. A request with
`{"include_judge": true}` also invokes the new RootLens Judge after each runtime
diagnosis. This is an explicit, potentially billable operation. The legacy
EchoMind evaluator remains available only through `{"mode": "legacy"}` and is
unchanged. No real paid Judge run is claimed in this batch.

The Judge sees the original case question, actual Agent response, operational
Evidence IDs and summaries, structured knowledge document IDs, and applicable
`diagnosis_points` and `forbidden_claims`. Expected labels are read only after
the diagnosis calls and never passed to Intent Recognition, tools, RAG, Agent,
or Memory. The Judge result is an evaluation, not a verified root cause.

## Judge rubric and result

Each dimension is scored on **0..1**:

- `evidence_grounding`: fidelity to operational Evidence and knowledge, with
  facts, Runbooks, and hypotheses distinguished.
- `diagnostic_reasoning`: plausible inference without treating correlation as
  proven causation; applicable diagnosis points may inform the assessment.
- `actionability`: concrete next checks or verification steps.
- `safety_and_uncertainty`: calibrated uncertainty and avoidance of unsupported
  or unsafe actions.

The strict JSON payload has exactly these four numeric scores plus a nonempty
`brief_reason`. `overall_score` is their arithmetic mean. The reported
`JudgeResult` also has `valid`, `raw_status`, `rationale`, and `error`.
Non-JSON output, missing/extra fields, wrong types, non-finite or out-of-range
scores, truncation, unexpected stop reasons, and API exceptions become invalid
results with no numeric score. They are never replaced by 0.5.

Judge `per_dimension_mean` and `overall_mean` average **valid cases only**.
`coverage = valid_cases / attempted_cases`; failed cases are counted separately.
When Judge is not requested, `status=not_run`, counts are zero, and coverage and
means are `null`. Deterministic metrics and Judge metrics must not be conflated.

## Baseline lifecycle

Ordinary `/eval/run` reads, but never writes, the RootLens approved baseline at
`ROOTLENS_APPROVED_BASELINE_PATH` (default
`/app/data/eval/rootlens/approved.json`). An absent file yields
`regression.status=no_baseline`. The old EchoMind `baseline.json` is untouched.

To approve a reviewed RootLens evaluation report, save the API JSON to a file
and explicitly run, from the app environment:

```bash
python -m evaluation.rootlens_baseline promote \
  --report /path/to/reviewed-report.json \
  --approved-path /app/data/eval/rootlens/approved.json
```

This local CLI creates a new immutable `history/<baseline_id>.json` snapshot
and atomically replaces the approved pointer. There is intentionally no
unauthenticated promotion endpoint. On the Windows host, choose report paths on
`E:`; the container path above is backed by the project's existing data mount.

The record contains suite name/version, runtime dataset ID/version, model and
provider identifiers, evaluation/Judge schema versions, case IDs, suite
fingerprint, creation time, deterministic and Judge metric snapshots, and Judge
valid/failed counts. A normal evaluation cannot silently approve itself.

## Regression comparison

Comparison requires matching suite name/version, dataset ID/version,
evaluation schema, Judge schema, case IDs, suite fingerprint, and whether Judge
was enabled. Mismatch yields `incompatible` with named reasons and **no deltas**.
Different model/provider is allowed but explicitly yields
`compared_model_changed` and `model_changed=true`; this is not represented as a
same-model regression. A corrupt approved file yields `invalid_baseline`.

For comparable metrics, `delta = current - baseline` on the 0..1 scale. An
absolute drop greater than 0.05 is `regressed`; an increase greater than 0.05
is `improved`; otherwise it is `stable`. Null values are `unavailable`.
Deterministic comparisons include intent accuracy, primary-agent accuracy,
supporting exact match, required-evidence coverage, clarification accuracy,
and runbook hit accuracy. Judge comparisons include each dimension mean,
overall mean, and valid-case coverage. The output reports each metric rather
than a single overall pass/fail.

## Limits

The six-case suite is a small smoke/regression suite, not a population-level
accuracy estimate. Judge scores have not yet been calibrated against human
review. A changed model is flagged but not made statistically equivalent.
When a judged run has failed cases, means cover only the valid subset; coverage
must be read alongside them. Stage 3-4 should perform a controlled real Judge
run and review the resulting responses, costs, and score validity before
promoting any baseline.
