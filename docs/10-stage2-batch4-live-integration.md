# Stage 2 第 4 批：Docker 与真实 LLM 联调

日期：2026-09-30。基线提交：`1488169`（Stage 2 第 3 批）。本批只做部署、真实请求验证及联调发现的一个窄范围 Skills 衔接修复；没有改业务数据、Router 阈值、RAG、Memory 或评测器。

## 环境与执行记录

- 工作目录：`E:\code\RootLens\app`。Docker Desktop 数据磁盘目录在 `E:\DockerData\DockerDesktopWSL`；本轮未在 C 盘创建项目或依赖缓存。
- Git 起始状态：仅 `chatgpt聊天结果.md`、`kun.doc`、`~$kun.doc` 三个既有未跟踪个人文件；本轮未改动或提交它们。
- `.env` 只检查键是否已配置，没有输出或记录密钥值。`ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`、`REDIS_PASSWORD` 已设置。RootLens 知识集合、画像与跨会话召回开关未显式设置，使用源码中的隔离默认值。
- `docker compose config --quiet`：退出码 0。
- `docker compose up -d --build`：退出码 0。应用镜像用已有依赖层缓存重建；RootLens 的 Redis、ChromaDB、Prometheus、Nginx 保持运行，`rootlens-app` 重建并变为 healthy。原 EchoMind Compose 未改动。
- 发现下面的 Skills 衔接问题后，只执行 `docker compose up -d --build echomind` 重建应用容器；再次 healthy。

## 真实请求

1. `GET http://localhost:8100/health`：200，`status=ok`。`GET /knowledge/stats`：4 个 RootLens 知识分片。`GET /skills`：4 份 RootLens Skills，无加载错误。
2. `POST /chat`：`payment-service 从 10:05 开始 5xx 激增，帮我判断原因`。用户未提供 DBConnectionError 或版本。真实意图为 `service_incident`，实体含 `service_name=payment-service`、`start_time=10:05`、`status_code=5xx`；来源分数为 LLM 0.95、Pattern 0.75、Embedding 0.0，不能宣称本次三路全启用。
3. 上述请求在 demo 模式显式采用 `2026-09-01 Asia/Shanghai`；三个现场工具状态均为 `ok`，共返回 9 个带稳定 ID 的日志、指标、发布证据，包括 10:00 发布及 10:05 的 DBConnectionError。RAG 的 rewrite/retrieval/rerank 均为 `performed`，`knowledge_used=true`。最终 Application 主、Database 辅，路由分数为 application 1.26、database 0.55；真实回复将连接获取失败与具体根因区分，并把发布关联标为待验证。两个 Agent 的模型调用均以 `end_turn` 正常结束，未截断。
4. `POST /chat`：`10:05 开始 5xx 激增，帮我判断原因`。`clarification_required=true`，要求补服务名；无 Agent 执行、无现场工具调用。
5. `POST /chat`：`payment-service 从 10:05 开始 5xx 激增`，`environment=prod`。`clarification_required=true`，要求完整日期，不猜 demo 日期；无现场工具调用。
6. `POST /chat`：`有没有数据库连接池故障的 Runbook？`。意图 `runbook_query`，知识命中，三个现场工具均未调用。Router 因原文含数据库/连接池关键词将主 Agent 选为 Database；这是当前路由规则的结果，不是一次现场诊断。请求后 Monitor 中三个现场工具的总调用数仍各为 1。
7. `GET http://localhost:8081/health` 经 Nginx 返回 ok；`GET http://localhost:8100/metrics` 返回 200 Prometheus 文本；`GET /monitor` 可读工具统计。

## 联调发现与修复

首次真实短请求虽然正确选择 Database 辅助 Agent，但只有 Application Skill 被注入。原因是原 `BaseAgent._build_system_prompt()` 仅用原始用户消息做关键词匹配；数据库错误码来自现场证据，不在用户消息中。

最小修复：只将 `Request.evidence_entities` 中经现场工具验证的错误码和版本作为额外 Skill 匹配词，不修改用户原 message、Intent 或 Router。补一项确定性回归测试后重建应用。第二次真实请求的日志确认：Application 与 Database Skills 均注入；路由仍为 Application 主、Database 辅，三个现场工具和 RAG 仍正常，Agent 均以 `end_turn` 完成。

## 非阻断观察与边界

- ChromaDB 客户端启动时有 PostHog telemetry 的 `capture() takes 1 positional argument but 3 were given` 错误；知识加载、实际检索和 `/chat` 均成功。本批未改第三方依赖。
- Monitor 在 Agent 正执行、计数已加但成功尚未记录时，短暂报告 Database 成功率 0.5；完成后为 1.0。另有平均延迟超过 3 秒阈值的告警，未阻断请求。本批未改监控计算或阈值。
- Agent 自然语言可能引用 `L001` 等短记录号；API `evidence_ids` 返回完整 ID。后续若要机器校验文本引用，需另做引用格式验证。
- 数据集与 Runbook 明确是模拟资料；没有验证真实生产日志/指标/发布平台连接或根因准确率。
- `/eval/run` 仍直接调用原 Orchestrator，不经过新 DiagnosisPipeline，不能用它宣称 Stage 2 全链评测通过。

## 测试与下一步

窄修复后运行第 3 批测试 21 项通过；使用单独的无持久化 Redis 容器跑全量 Stage 1、Stage 2-1、Stage 2-2、Stage 2-3 回归：**115 passed，0 skipped**。测试容器已停止。真实 HTTP 核心链已通过，但这不是生产部署或根因准确率验收。后续优先让 Evaluation 对新管线使用统一案例，再考虑结构化 IncidentDiagnosis 和 Trace；本批不进入这些实现。
