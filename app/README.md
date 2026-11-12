# RootLens 后端

FastAPI 后端接收告警描述，查询版本化模拟证据并检索 Runbook，组织主辅 Agent 分析，返回结构化诊断和执行轨迹。先按[仓库首页](../README.md#本地运行)构建前端、填写本地环境变量并启动 Compose。

| 入口 | 用途 |
| --- | --- |
| [控制台](http://localhost:8081/console/) | 提交告警、查看证据与结果 |
| [Swagger](http://localhost:8081/docs) | 查看健康检查、诊断与评测接口 |
| `/chat` | 运行一次诊断或继续澄清 |
| `/eval/run` | 使用固定案例验证共享诊断流程 |
| `/diagnoses` | 在启用历史访问后查询诊断档案 |

Redis 保存会话工作记忆，ChromaDB 保存 Runbook，SQLite 保存诊断历史。现场取证使用合成事件数据，普通 `/chat` 请求不开放测试专用故障注入。启用历史访问时，在 `.env` 中设置 `ROOTLENS_HISTORY_API_ENABLED=true` 和 `ROOTLENS_HISTORY_API_TOKEN`，用该令牌在控制台解锁。模型 API Key 只用于后端模型配置。共享令牌适用于受控本地演示。

[五分钟演示](../docs/30-stage7-closeout-and-demo.md) · [控制台使用说明](../frontend/README.md) · [Skills 配置](skills/README.md) · [项目来源](../docs/project-origin.md)
