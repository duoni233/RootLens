# EchoMind 到 RootLens 的改造映射表

## 1. 项目定位

| EchoMind | RootLens |
|---|---|
| 多 Agent 客服编排运行时 | 多 Agent 系统异常诊断平台 |
| 面向用户咨询、退款、技术支持 | 面向内部服务故障、告警排查、运行诊断 |
| 输出客服回复 | 输出结构化 IncidentDiagnosis + 处置建议 |

## 2. Agent 映射

| EchoMind | RootLens MVP | 说明 |
|---|---|---|
| GeneralAgent | GeneralOpsAgent | 问题澄清、告警分级、总结 |
| TechnicalAgent | ApplicationAgent | 应用错误、接口异常、发布问题 |
| BillingAgent | DatabaseAgent | 数据库/数据链路问题，替代原账务域 |
| 暂无 | InfrastructureAgent | 第二阶段加入基础设施诊断 |

## 3. Intent 映射

| EchoMind Intent | RootLens Intent |
|---|---|
| logistics / request / account | runbook_query / alert_triage |
| technical_login / technical_crash | service_incident / latency_issue / deployment_issue |
| refund / invoice / payment_issue | database_issue / resource_issue |
| human_handoff | human_escalation |
| greeting | greeting |
| unknown | unknown |

## 4. Entity 映射

| EchoMind Entity | RootLens Entity |
|---|---|
| order_id | trace_id / request_id / incident_id |
| amount | latency / error_rate / metric_value |
| invoice_title | service_name / env |
| email / phone | owner / team |
| error_code | error_code / status_code |

## 5. RAG 数据映射

| EchoMind | RootLens |
|---|---|
| 退款政策 | Runbook / SOP |
| 配送说明 | 服务架构文档 |
| 技术排障 FAQ | 历史 Incident / Postmortem |
| 会员规则 | 服务依赖关系 / 发布记录说明 |

## 6. Tools 映射

| EchoMind Tool | RootLens Tool |
|---|---|
| knowledge_search | search_runbooks |
| 无 | query_logs |
| 无 | query_metrics |
| 无 | query_deployments |
| 无 | query_incidents |

## 7. 需要保留的工程能力

```text
FastAPI
Docker Compose
Redis working memory
ChromaDB RAG / episodic / profile
IntentRecognizer 三路融合思想
AgentOrchestrator primary/supporting routing
SkillManager dynamic rules
Tool timeout/cache/circuit breaker/fallback
Monitor routing penalty
Evaluation LLM-as-Judge
```

## 8. 需要新增的工程能力

```text
Pydantic IncidentDiagnosis schema
Execution Trace
Failure Injection
pytest / pytest-asyncio
统一 Incident Dataset
SQLite for incident / trace / eval runs，稍后再考虑 PostgreSQL
```

## 9. MVP 验收标准

一次请求如：

```text
payment-service 从 10:05 开始 5xx 激增，刚发布 v2.3.7，日志里有 DBConnectionError，帮我判断原因
```

系统应能：

```text
1. 识别为 service_incident + deployment_issue + database_issue
2. 抽取 payment-service / 10:05 / v2.3.7 / DBConnectionError
3. 检索相关 runbook 和历史 incident
4. 调用模拟 logs / metrics / deployments 工具
5. 路由 ApplicationAgent 为主，DatabaseAgent 为辅
6. 输出结构化 IncidentDiagnosis
7. 记录 Execution Trace
8. 被 evaluation case 自动验证
```
