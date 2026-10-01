# RootLens Stage 3-2 验收记录

日期：2026-10-01。范围：Evaluation 对齐 Intent Recognition + DiagnosisPipeline 核心链；不改 Judge、baseline、Router 或 Stage 2 诊断逻辑。

## 1. 实际调用链

`/chat` 与默认 `/eval/run` 共同调用 `core/diagnosis_entry.py:run_diagnosis`：

```text
message + 本案例历史 + 可选 environment/anchor_time
  -> 同一个 AgentOrchestrator.recognize_intent
  -> 同一个 DiagnosisPipeline.run
  -> IntentResult + DiagnosisOutcome
  -> EvaluationObservation
  -> 全部案例执行结束后才读取 ExpectedResult，计算确定性指标
```

`/chat` 仍在 API handler 中读写 Redis；Evaluation 不读写 Redis，每个案例使用独立 user_id/conv_id，历史仅限本案例。多轮案例取最后一轮 Observation 评分。旧 `EndToEndEvaluator` 未删除，仅显式 `mode=legacy` 才使用；RootLens 默认路径标记 `judge_status=not_run`，不调用旧 Judge、不自动保存 baseline。

评测案例文件不进入镜像（`.dockerignore`）；Compose 仅将 `stage3-v1.json` 只读挂载到 `/eval-data`。运行态 IncidentTools 仍只允许 `datasets/runtime` 白名单路径。测试证明 expected 不进入意图识别、工具参数、RAG 查询或 Agent 上下文。

已知边界：本批隔离的是 Redis 会话和案例历史，不是在线调用统计。Evaluation 与 /chat 复用同一 Orchestrator/ToolManager 实例，Agent/Tool 成功率与延迟统计可能计入 Monitor；要做不影响在线监控的基准评测，需要独立运行实例或后续单独设计评测模式，本批不改监控链。

## 2. 真实 HTTP 联调

重建仅应用容器后，调用 `POST http://localhost:8100/eval/run`（空请求体）。下表来自真实配置的意图识别与 Agent 模型调用；非 LLM Judge 评分。现场数据为明确标注的模拟故障集。

| 案例 | 实际 Intent | 实际主/辅 Agent | Evidence | Tool 状态 | Runbook | 澄清 |
| --- | --- | --- | ---: | --- | --- | --- |
| INC-001 | deployment_issue | application / database | 9 | ok/ok/ok | DB、APP、DEP | 否 |
| INC-002 | service_incident | application / 无 | 2 | ok/ok/empty | APP、DEP、DB | 否 |
| INC-003 | resource_issue | infrastructure / 无 | 2 | ok/ok/empty | APP、DEP | 否 |
| runbook-db-pool | runbook_query | database / 无 | 0 | 未调用 | DB、APP | 否 |
| clarify-missing-service | service_incident | 未执行 Agent | 0 | 未调用 | 无 | 是 |
| INC-004-partial | service_incident | application / 无 | 1 | empty/ok/empty | APP、DEP、DB | 否 |

三个 Tool 状态依次为 logs / metrics / deployments。RAG 在五个非澄清案例中为 `retrieval=performed`，澄清案例为 `skipped`。INC-001 意图与预期 service_incident 不符；未为提高分数修改案例或模型逻辑。

| 确定性指标 | 分子 / 分母 | value |
| --- | ---: | ---: |
| intent_accuracy | 5 / 6 | 0.8333 |
| intent_macro_f1 | 2.8571 / 4 类 | 0.7143 |
| primary_agent_accuracy | 4 / 4 | 1 |
| supporting_agent_exact_match | 4 / 4 | 1 |
| supporting_agent_partial_match | 4 / 4 | 1 |
| evidence_required_coverage | 9 / 9 | 1 |
| tool_status_accuracy | 6 / 6 | 1 |
| clarification_accuracy | 6 / 6 | 1 |
| runbook_hit_accuracy | 3 / 3 | 1 |
| forbidden_claim_violation_count | 0 / 2 检查项 | 0 次 |

指标限制：必需 Evidence 覆盖率没有衡量额外无关证据；Runbook 命中率只验证必需文档出现，不衡量检索精度，表中多例有额外 Runbook；禁止断言是文字匹配，不是语义安全评测。六例只构成小型回归集，不代表统计总体性能或根因诊断准确率。

## 3. 验证边界

- `docker compose config --quiet` 通过；应用容器重建后健康。
- 离线集成测试使用受控 LLM/Agent 替身，真实运行取证工具与 Router；不应将离线满分当作真实模型成绩。
- 全量 pytest：142 passed（Stage 1/2/3-1 原有 133 项 + Stage 3-2 新增 9 项）。
- `data/eval/baseline.json` 联调前后 SHA-256 均为 `971BFD1BBF0E77C68EF631B6A2378552A0756F06655EA5FF20C72636F5A82EA1`。
- Stage 3-3 才处理旧 Judge 的客服 rubric、失败填 0.5、结构化评分，以及 baseline 的版本化和显式更新；本批不进入该阶段。
