# Stage 2 第 3 批验收：共用诊断管线

日期：2026-09-30。代码与确定性集成测试通过；当前运行中的 RootLens 容器仍是旧镜像，本批未做真实 LLM /chat 验收。

## 本批改动

| 文件 | 作用 |
| --- | --- |
| `app/core/evidence.py` | 从实体、可选环境和完整时间建立 QueryContext；只有 demo 缺日期时使用 2026-09-01，并显式记录假设；冲突或缺关键条件时澄清 |
| `app/core/routing_signals.py` | 只从状态为 ok 的现场证据提取领域分数下限、来源 ID 和证据实体；重复记录不累计评分 |
| `app/core/diagnosis_pipeline.py` | 共用顺序：Gate、三工具并行取证、增强 query、知识检索、构造 Request、调用 Orchestrator.run 一次 |
| `app/agents/agent_orchestrator.py` | Request 增加证据上下文/证据实体/路由信号；原领域分数与证据下限按 max 合并；Agent 区分事实、知识和假设 |
| `app/api/main.py` | 启动时注册三个现场工具；/chat 调用管线并返回证据、状态和假设；旧响应字段保留，原 RAG 格式化逻辑保留兼容 wrapper |
| `app/test_rootlens_diagnosis_pipeline.py` | 第 3 批固定集成案例与 HTTP 契约测试 |

没有改 IntentRecognizer、工具框架、RootLens 知识库和 Memory 实现，也没有接 IncidentDiagnosis、Trace、数据库或前端。

## 当前 /chat 链路

```text
Redis 当前会话 -> Intent/Entity
  -> 诊断意图 Gate（Runbook/问候不取现场证据）
  -> QueryContext（服务、环境、完整时间、窗口）
  -> query_logs / query_metrics / query_deployments 并行
  -> EvidenceBundle（ok/empty/failed/degraded）
  -> 有来源的日志词增强 RAG query -> RootLens Runbook 检索
  -> operational evidence 生成 routing_signals
  -> Request（原消息、原实体、记忆、现场事实、知识、工具状态）
  -> Orchestrator.run -> 一次最终主辅选择 -> Agent 回复
  -> Redis 写入
```

只有 operational evidence 且对应工具状态为 ok 才能抬高领域分数。DBConnectionError 可给 Database 0.55 下限，5xx 异常给 Application 0.75，下限与原分数取 max，不是概率置信度。成功发布只产生应用相关线索，不能直接证明根因。Knowledge/Runbook 不产生路由信号；用户实体、证据实体和待验证假设不混写。

`/chat` 可选请求字段：`environment`（demo/staging/prod）和带时区的 `anchor_time`。只给 10:05 时，默认 demo 使用固定模拟日期并在 `query_context.assumptions` 明示；非 demo 缺完整日期、缺服务或时间冲突会澄清，不全库扫描。响应新增 `evidence_ids`、`tool_status`、`tool_errors`、`query_context`、`rag_stage_status`、`evidence_entities`、`routing_signal_sources`、`clarification_required`。原响应字段保持。

## 验证边界

新增 20 项测试覆盖：简短请求通过工具发现 DBConnectionError、一次路由、主辅 Agent、10:00 发布前向召回、runbook 跳过三工具、告警 Gate、缺条件/时间冲突澄清、empty/failed/degraded、重复日志去重、知识证据不打分、expected 文件隔离、真实 Chroma 测试集合检索、fallback 非知识命中，以及 FastAPI /chat 响应结构。

完整测试在已有 RootLens 镜像加只读源码挂载中运行；pytest 来自 E 盘离线 wheel。原有三项 Redis 事务测试使用临时无持久化 Redis 容器，结束后已停止。结果：**114 passed，0 skipped**（Stage 1 15 + Stage 2-1 37 + Stage 2-2 42 + Stage 2-3 20）。测试中的 LLM/Agent 回复使用替身；没有调用真实模型。

当前运行的 `rootlens-app` 未重建，不能把本批测试结果称为真实部署验收。`/eval/run` 仍直接调用原 Orchestrator，未经过新管线，不能代表 Stage 2 端到端评测。真实模型的意图融合、RAG 改写/重排、长回复质量与全部容器启动仍待第 4 批验证。下一步建议做 Stage 2 第 4 批 Docker 构建和真实 /chat 联调，失败时停在具体层分析，不扩大功能范围。
