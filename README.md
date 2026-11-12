# RootLens：基于证据的故障诊断演示系统

RootLens 是一个面向内部服务故障的智能诊断演示系统。用户描述异常后，系统查询**模拟**日志、指标和发布记录，检索 Runbook，选择主/辅 Agent，输出带证据引用的结构化诊断，同时记录执行过程和本地历史。

当前 `rootlens-demo:v2` 运行数据包含四组模拟事件，评测套件包含六个案例（含 Runbook 问答与澄清）；**没有连接 staging 或生产系统**。六案例回归用于发现版本退步，不能代表真实故障诊断准确率。

## 一次请求经过哪里

```text
React 控制台 -> FastAPI /chat
  -> Intent / RootLens Entity -> 是否需要现场取证
  -> 时间窗口内的 logs / metrics / deployments
  -> Evidence 增强的 Runbook 检索
  -> 一次主/辅 Agent 路由 -> 自然语言回复
  -> IncidentDiagnosis 校验 + DiagnosisTrace
  -> SQLite DiagnosisRun 保存 -> 历史详情 / Trace
```

`/eval/run` 复用核心诊断链，以独立的 expected 数据比较六案例结果。测试专用故障注入不对普通 `/chat` 开放。Redis 保存当前会话工作记忆；ChromaDB 保存 RootLens 知识；SQLite 保存诊断历史，三者职责不同。

## 本地运行

需要 Docker Desktop / Compose、Node.js/npm 和一个 Anthropic 兼容的模型接口。把 `app/.env.example` 复制为 `app/.env`，在后者填写模型凭据；**不要提交 `.env`**。以下命令在 E 盘项目目录运行，npm 缓存也放在 E 盘：

```powershell
cd E:\code\RootLens\frontend
npm ci --cache E:\Codex\cache\npm
npm test
npm run build

cd E:\code\RootLens\app
docker compose up -d --build
docker compose ps
```

打开[诊断控制台](http://localhost:8081/console/)或 [Swagger 接口文档](http://localhost:8081/docs)。Nginx 挂载预先构建的 `frontend/dist`；前端改动后需重新构建。历史 API 默认关闭，私有演示需要在 `app/.env` 中单独启用并设置 `ROOTLENS_HISTORY_API_TOKEN`。**历史令牌不是模型 API Key**；当前 HTTP + 共享令牌不属于生产级认证。

可输入一条 demo 故障（Asia/Shanghai，模拟日期为 `2026-09-01`）：

> payment-service 从 10:05 开始 5xx 激增，刚发布 v2.3.7，帮我判断原因。

预期检查的是行为而非固定措辞：能向前查到 10:00 发布、找到 5xx 和连接池证据、由 Application 主诊断并让 Database 辅助，并把“发布可能相关”留作**待验证假设**。事件时间可以手动修改；直接填电脑今天的日期，可能查不到这份历史模拟数据。

历史记录有两种不同操作：“解读已有记录”只把该条已保存的结构化诊断和新问题交给配置模型，不重新取证；“重新诊断”是新一次 `/chat`，会重新查询 demo 数据。旧记录解读不是当前现场结论。

## 验证与边界

- Stage 5 保存的真实六案例验收：结构化诊断 6/6、Judge v2 有效 6/6；这是合成案例结果，不是独立生产基准。
- Stage 6 验证了 SQLite 在应用重启/重建后的历史保存，以及带访问边界的列表、详情和 Trace API。
- Stage 7 最新记录为前端 22 项、隔离环境后端 322 项测试通过。一次真实模型的历史解读 API 冒烟测试能区分事实/假设，并未把发布时间相邻断言为根因。浏览器双模式追问仍待 Owner 最终确认，不能提前宣称 Stage 7 正式关闭。
- 现场工具只查版本化 JSON 模拟数据；RAG 仍有额外命中；Judge 尚未经过大规模人工校准；未做生产负载、故障恢复或租户隔离研究。历史只保存部分来源引用，不是完整不可变审计日志。


继续阅读：[先看中文架构图与请求流程](docs/33-rootlens-architecture-walkthrough-cn.md)、[中文项目口述与技术取舍](docs/31-project-interview-cn.md)、[基于作者面经改写的 RootLens 问答](docs/32-rootlens-interview-qna-cn.md)、[五分钟演示与待验项](docs/30-stage7-closeout-and-demo.md)、[逐阶段验收](docs/03-progress.md)。
