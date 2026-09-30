# RootLens Stage 3 Evaluation Design v0.1

状态：仅实施 Stage 3-1 的契约、数据和确定性指标；不接入旧评测接口。本文件明确区分源码事实与后续计划。

## 中文速览

**源码事实：** `/chat` 已走意图识别、DiagnosisPipeline、现场取证、RAG 和一次最终路由；`/eval/run` 仍绕过该管线，直接运行 Orchestrator 和客服版 Judge。现有默认案例也仍是退款等客服问题。Judge 解析失败后填入 0.5，且每次评测会覆盖 baseline。因此旧报告不能作为 RootLens 诊断质量结论。

**Stage 3-1 已批准的设计：** 标准答案放在独立 evaluation 数据目录；向运行管线只投射消息、环境和时间。先建立六个小案例、可追溯的 synthetic 运行态记录、无需 LLM 的分层指标和测试。KnowledgeResult 仅新增结构化来源观察字段，不改 Agent 所见文本。

**后续计划：** Stage 3-2 才让 Evaluation 复用真实诊断管线；Stage 3-3 才处理 RootLens Judge、无效评分和显式批准的版本化基线。本批不修改 `/eval/run`、Router 阈值或 Stage 2 主逻辑。

## Current source behavior

- `app/api/main.py:/chat` reads current-session memory, recognizes intent, calls `DiagnosisPipeline.run`, writes memory, and returns evidence IDs, tool states, routing and RAG states.
- `app/api/main.py:/eval/run` passes old customer-service default cases to `EndToEndEvaluator`.
- `IntentEvaluator` independently scores intent accuracy and Macro-F1; its `context` field is not used in recognition.
- `EndToEndEvaluator._evaluate_dialog_case` invokes `AgentOrchestrator.run` directly. It does not exercise evidence acquisition, RootLens RAG, evidence-aware routing or `/chat` memory writes.
- `LLMJudge` uses a customer-service rubric. Missing JSON fields and exceptions become 0.5; failed scores still enter averages.
- Every evaluator run saves `data/eval/baseline.json`, so the baseline is not an immutable approved reference.
- Current RootLens runtime fixtures cover only `INC-001`; existing evaluation labels live outside the runtime directory and are not read by `IncidentTools`.

## Proposed target (not yet implemented)

`/eval/run` should use the same intent-recognition and `DiagnosisPipeline` core path as `/chat`, then compare the observed intent, evidence, tool states, structured knowledge IDs, route and answer with private expected labels. The evaluator must not pass labels to the pipeline, tools, RAG or agents. Reusing the core pipeline alone does not reproduce Redis reads/writes; memory parity is a separate decision.

## Stage 3-1 contract

`EvaluationCase` has `case_id`, exactly one of `message` or `messages`, optional `environment` and aware `anchor_time`, and `expected: ExpectedResult`. The expected fields are optional per case: `intent`, `primary_agent`, `supporting_agents`, `evidence_ids`, `evidence_types`, `tool_status`, `runbook_ids`, `diagnosis_points`, `forbidden_claims`, and `clarification_required`. A runtime-input projection exposes only message, environment and anchor_time. The evaluation dataset is a separate file under `datasets/evaluation`; runtime incidents remain under `datasets/runtime`.

## First case set

1. `INC-001`: payment-service 5xx after deployment with DB pool evidence; Application primary, Database supporting, DB runbook. Do not assert that deployment caused the fault.
2. Synthetic application-only 5xx with no database evidence.
3. Synthetic CPU/resource anomaly for Infrastructure routing.
4. Runbook query without operational tools.
5. Missing service or full non-demo date, requiring clarification without a full scan.
6. Partial evidence: one empty tool and another with records. Failed/degraded tool behavior is a controlled test-double scenario, not a claimed runtime incident.

The small set is a regression/sanity suite, not a statistical performance estimate. Cases 2 and 3 require actual consistent synthetic runtime records, not labels alone.

## Deterministic metrics

All metrics report numerator, denominator and `null` when no cases apply. Absent expected fields are skipped, not failures.

| Metric | Numerator / denominator |
| --- | --- |
| intent_accuracy | Correct labeled intents / labeled intent cases |
| intent_macro_f1 | Mean per-class F1 over labels present in expected or prediction, using labeled cases only |
| primary_agent_accuracy | Correct primary agent / cases with expected primary agent |
| supporting_agent_exact_match | Equal supporting-agent sets / cases with expected set, including an explicitly empty set |
| supporting_agent_partial_match | Mean per-case Jaccard overlap; both sets empty scores 1; cases with expected set only |
| evidence_required_coverage | Required IDs found / required IDs across labeled cases |
| tool_status_accuracy | Exact expected status map / cases with an expected map; an explicitly empty map means no operational tool calls |
| clarification_accuracy | Correct Boolean / cases with expected clarification Boolean |
| runbook_hit_accuracy | All required runbook document IDs observed / cases with expected runbook IDs |
| forbidden_claim_violation_count | Numerator and value are the number of forbidden literal claims; denominator is the number of labeled forbidden phrases checked |

Diagnosis points are recorded but are not semantically scored in Stage 3-1. Runbook matching uses structured document IDs, never prompt text. Literal forbidden-claim matching is only a deterministic guard, not a semantic safety guarantee.

## Risks and staged implementation

- Stage 3-1: add contracts, isolated case data, structured knowledge source observations, deterministic metrics and tests. Do not change `/eval/run` or baseline.
- Stage 3-2: connect evaluator to the existing core diagnosis path, retain expected-label isolation, and expose per-layer results. Define any memory coverage explicitly.
- Stage 3-3: adapt the RootLens Judge rubric, validate complete finite scores, mark failures unavailable rather than 0.5, and compare only explicitly promoted baselines for compatible suite/model/data versions.

No Stage 3-1 metric should be interpreted as a measured quality result until the evaluator actually runs the shared diagnosis path.
