# Stage 6A Diagnosis Persistence Foundation

日期：2026-10-04。状态：**Foundation completed；尚未接入运行时**。

## 实施前审计

- 项目此前没有 SQLAlchemy、SQLite 诊断库、Repository、ORM 或 Alembic；Redis 是会话工作记忆，ChromaDB 是知识与情景数据，`app/data/eval/` 是评测报告及 approved baseline，均不是普通诊断历史。
- `core.diagnosis_entry.run_diagnosis` 被 `/chat` 与 RootLens Evaluator 共用。`DiagnosisOutcome` 包含编排结果、结构化构建结果和可选 `DiagnosisTrace`；因此本批没有在共用函数或 Pipeline 中写数据库，也没有更改 `/eval/run`。
- 保存边界放在独立 `persistence/` 包。Stage 6B 才能由 `/chat` 显式调用，避免评测案例进入用户历史。

## 数据契约与存储

`DiagnosisRun v1` 是一次已完成诊断的历史记录，其 `run_id` 独立于编排 `request_id`、会话 `conversation_id` 和 Trace `trace_id`。一张 `diagnosis_runs` 表保存 UTC 时间、原始请求、服务/环境、Intent、主辅 Agent、Markdown、构建/Trace 状态、degraded/clarification 标记，以及 JSON 快照。创建时间、服务、诊断状态、degraded 有索引；列表支持 `limit/offset` 和这三项筛选，按创建时间倒序并用 `run_id` 固定同时间顺序。

`IncidentDiagnosis v1` 与 `DiagnosisTrace v1` 使用各自完整的 versioned JSON 快照；Reader 在反序列化前检查版本，未知版本明确报错，不静默按 v1 解释。SQLite 用 JSON 序列化文本，Repository 隐藏该实现。第一版仅有单表，`create_all` 负责初始化，不引入迁移框架。数据库 URL 由调用方显式提供；初始化时仅创建配置 URL 指向的 SQLite 父目录。测试使用独立临时库；Stage 6B 再配置 Docker 的持久化挂载与本地 E 盘路径。

转换层只投影明确字段。成功、澄清、Tool 降级、Agent 降级、Assembler parse/validation/API 失败以及 `diagnosis=null` 但 Markdown 有效，均可形成记录。Agent 每次执行的完整 `content`、隐藏 Prompt、模型上下文和异常堆栈没有单独保存。Operational Evidence 仅保留 ID/来源类型，Knowledge 仅保留 document/chunk ID 与 `source_ref`；不复制原始日志、指标载荷或 Runbook 正文。这降低了重复与隐私风险，但未来若源数据变更，单凭引用不能完整重现历史源内容，Stage 6B/7 展示方案须承认这一边界。

`DiagnosisRun` 拒绝带 `eval_run_id` 的 Trace；本批也没有任何自动写入钩子。Repository 写入错误明确抛出，**不**伪装为已保存。未产生 `DiagnosisOutcome` 的未捕获异常尚不能转成历史记录。原始用户消息和最终 Markdown 本身可能含敏感信息，Stage 6B 对外开放历史 API 前必须确定访问边界、保留/脱敏策略和数据库失败时 `/chat` 的响应语义；不得把普通用户历史公开列出。

## 验证与下一步

- 新增直接依赖 `SQLAlchemy==2.0.36`。测试在一次性 Docker 容器中安装该依赖，不重建或改变正在运行的 `rootlens-app`。
- 新增 17 项确定性测试：SQLite 初始化与隔离、保存/读取/排序/筛选、结构化诊断和 Trace 往返、澄清/降级/结构化失败、未知 schema、评测隔离和私有 Agent 内容排除。
- 全量 Stage 1–6A 离线回归在隔离临时 Redis 下通过 **303 passed，0 skipped**；未调用真实 LLM/Judge。测试 Redis 容器与网络已移除。
- Stage 5 approved baseline `f79e1d913c7146088805290f7e1580e3` 未改动；旧历史快照也未改动。

**建议进入 Stage 6B**：由 `/chat` 显式保存并返回 `run_id`/真实保存状态，提供有访问边界的分页历史列表与详情 API，配置 Docker 持久化目录，然后做真实容器及全量回归验收。本批没有完成这些工作，也未开始 Stage 7 前端。
