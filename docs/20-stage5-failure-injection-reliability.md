# Stage 5-2: Controlled Failure Injection and Reliability

Status: offline scenarios accepted. No production failure injection, full
Trace API, real LLM acceptance, or Stage 3 baseline promotion occurred.

## Boundary and controller

`app/test_support/failure_controller.py` contains the only failure plans. It
is imported by pytest, not the runtime entry, `/chat`, or `/eval/run`. Each
`FailurePlan` validates a fixed target/failure pair before execution. Its
context manager replaces one component at an existing test boundary and
restores the original handler, timeout, cache, Agent, or model method on exit.
Each scenario creates fresh ToolManager/Orchestrator instances; cache is
disabled for controlled tool runs. There is no random probability, runtime
dataset mutation, expected-label mutation, user-supplied injection parameter,
or conditional failure branch in business code.

The controller never imports or writes `TraceStep`. It changes what a component
does; the ordinary Pipeline, ToolManager, Orchestrator, Assembler, and Trace
Recorder produce the observed state.

## Scenarios and observed behavior

| Scenario | Controlled component behavior | Observed containment |
| --- | --- | --- |
| `logs-timeout` | `query_logs` exceeds ToolManager timeout | Logs Trace failed; metrics/deployments and RAG succeeded; no log Evidence; Markdown and degraded structured diagnosis survived. |
| `metrics-exception` | `query_metrics` handler raises | Metrics Trace failed; logs/deployments succeeded; no metric Evidence; usable degraded diagnosis survived. |
| `logs-empty` | `query_logs` returns `[]` | Trace `success + empty`; no log Evidence; overall and structure remained non-degraded. This is a boundary case, not a true injected failure. |
| `rewrite-exception` | RAG rewrite model call raises | Rewrite Trace degraded; original query was retrieved; RAG retrieval succeeded; final result was degraded. |
| `retrieval-exception` | Knowledge Tool raises | RAG retrieval Trace failed; operational Evidence and Agent reply survived; no Knowledge sources/refs were invented. |
| `supporting-exception` | Database Agent `handle` raises | Parallel Application result survived; Database attempt and `AgentExecutionRecord` failed; structured result was degraded and noted the missing auxiliary opinion. |
| `primary-fallback` | Application Agent returns a failed response | Failed Application and successful GeneralOps fallback are separate attempts; fallback Markdown survived; overall and structured results were degraded. |
| `assembler-json` | Model returns malformed JSON | `parse_failed`, `diagnosis=null`, assembly Trace failed, Markdown retained; overall degraded. |
| `assembler-api` | Assembler model call raises | `assembler_failed`, `diagnosis=null`, assembly Trace failed, Markdown retained; overall degraded. |
| `validation-unknown-id` | Assembler cites unknown Evidence ID | `validation_failed` with `run_scope_validation_failed`; no diagnosis object or invalid source ref escaped; Markdown retained. |
| `normal` | No failure plan | Tool, RAG, routing, Agent and assembly behavior remained successful. |
| `clarification` | Missing service name | QueryContext requested clarification; Tools/RAG/routing/Agent skipped; deterministic assembly succeeded without an LLM call; overall success, not degraded. |

The primary fallback scenario deliberately uses a **failed Agent response**,
because that is what the current `_execute` fallback branch handles. A direct
uncaught `handle()` exception is not claimed to exercise this fallback.

## Independent Stage 5 report and metric denominators

`evaluation/rootlens_reliability.py` creates `ReliabilityScenarioResult` and
`ReliabilityReport` after each runtime diagnosis completes. Each scenario
records the injected target/type, Trace status, expected/actual overall status,
degraded flags, fallback observation, response preservation, diagnosis build
status, invalid source refs, and individual assertion outcomes. The report is
independent of the Stage 3 metrics map, Judge, approved baseline, and
regression comparator.

| Metric | Numerator / denominator | Observed |
| --- | --- | ---: |
| `failure_detection_accuracy` | True injected failures with correct component/status/error code / 9 true failures; excludes empty and controls | 9/9 |
| `degraded_flag_accuracy` | Correct Trace and, when present, structured diagnosis degraded flag / all 12 scenarios | 12/12 |
| `fallback_observed_accuracy` | Failed original and successful GeneralOps attempt both visible / 1 fallback scenario | 1/1 |
| `failure_containment_success_rate` | Usable response, unaffected steps, expected status/degradation, expected fallback, no invalid source, and correct build status / all 12 scenarios | 12/12 |
| `skipped_step_accuracy` | Correctly skipped steps / 8 expected skipped steps in clarification | 8/8 |
| `invalid_source_after_failure_count` | Count of invalid Evidence/Knowledge refs across failure scenarios / 9 true failures inspected; value is a **count**, not a percentage | 0/9; value 0 |

Fields not applicable to a scenario are excluded from their metric denominator.
An empty denominator has a `null` value, not a fabricated perfect score.
These numbers describe **12 deterministic, synthetic test scenarios only**.
They do not estimate recovery success across production incidents or providers.

## Verification and remaining limits

The 16 new tests include 10 parametrized component/boundary scenarios,
clarification, normal-path safety, controller cleanup/fail-fast behavior,
the 12-scenario report, and metric denominator/negative-control checks.
Full offline regression: **270 passed, 3 skipped, 0 failed** in a disposable
Docker container using E-drive wheel cache and a read-only source mount.
All three skips are from `test_rootlens_knowledge_memory.py:501` because the
isolated Redis test service was not configured in that container. The live
RootLens app was not rebuilt and no paid LLM/Judge was called.

The Stage 3 six-case synthetic suite, Judge rubric, approved baseline and
comparator were not changed. `IncidentDiagnosis v1`, `/chat` response fields,
Router thresholds, Intent taxonomy, RAG ranking, Agent prompts and Evidence
dataset were not changed. Existing Stage 1-5 tests passed.

Not yet covered: a primary Agent's uncaught exception outside the successful
fallback contract, circuit-breaker recovery/half-open timing, RAG rerank
failure, external Redis/Chroma outages, real provider failures, and
production-scale concurrent load. These are not silently counted as passing
scenarios. Stage 5-3 may evaluate selected boundaries in controlled Docker
conditions and decide whether/how to expose a safe debug Trace view; it must
not expose a public failure-injection API.
