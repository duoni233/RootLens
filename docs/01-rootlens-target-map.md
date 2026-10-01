# RootLens 目标模块图

> 项目定位：RootLens 是一个面向企业内部系统异常、服务故障和运营问题的多 Agent 智能诊断平台。

## 1. 最小目标链路

```text
用户提交故障/告警描述
  -> FastAPI /diagnose 或兼容 /chat
  -> 读取 session memory + historical incidents + service profile
  -> Intent + Entity Extraction
  -> 按意图决定检索 Runbook / Incident / Architecture docs
  -> Tool calls
       -> query_logs
       -> query_metrics
       -> query_deployments
       -> search_runbooks
  -> Agent Router
       -> primary_agent
       -> supporting_agents
       -> routing_reason
  -> Application / Database / Infrastructure Agent
  -> Synthesis
  -> IncidentDiagnosis structured output
  -> Execution Trace
  -> Evaluation + Regression
```

## 2. Agent 初始设计

```text
GeneralOpsAgent
  -> 负责问题澄清、告警分级、跨域总结

ApplicationAgent
  -> 负责应用错误、接口异常、版本发布、异常日志

DatabaseAgent
  -> 负责慢查询、连接池、锁等待、数据库错误

InfrastructureAgent
  -> 负责 CPU/Memory/Disk/Network/Nginx/Redis 等基础设施问题
```

MVP 阶段可以先保留 3 个 Agent：`general_ops / application / database`，Infrastructure 作为第二阶段加入。

## 3. 核心 Intent

```text
service_incident      主要调查服务异常本身（如 5xx 激增），未明确聚焦变更关联
latency_issue         延迟升高或超时
database_issue        数据库慢查询、连接池、锁等待
deployment_issue      主要调查近期发布、版本或配置变更与异常的关联
resource_issue        CPU/内存/磁盘/连接数异常
network_issue         网关、Nginx、DNS、网络抖动
runbook_query         查询处理手册或 SOP
alert_triage          告警分级与初步判断
human_escalation      需要人工介入
unknown               无法判断
```

当前 Intent 为单个主标签，按用户**当前主要调查焦点**分类，不只按症状词分类。
“payment-service 5xx 激增”属于 `service_incident`；“发布 v2.3.7 后开始 5xx，调查两者关联”属于 `deployment_issue`。
仅说“不确定是否与发布有关”、主要仍在询问服务异常时属于 `service_incident`。
时间先后不等于因果；该分类不表示发布已被证明为根因。

RootLens 当前运行态实体投影仅允许 `date`、`service_name`、`start_time`、`version`、`status_code`、`error_code`，并过滤空值与和旧客服实体重合的值。下方实体清单是目标设计，不代表均已实现。

## 4. 核心 Entities

```text
service_name
error_code
trace_id
request_id
version
env
time_window
host
pod
metric_name
latency
status_code
```

## 5. 结构化输出

```json
{
  "incident_id": "INC-001",
  "severity": "P1",
  "affected_service": "payment-service",
  "primary_domain": "application",
  "suspected_causes": [
    {"cause": "database_connection_pool_exhausted", "confidence": 0.86}
  ],
  "evidence": [
    "5xx increased after deployment v2.3.7",
    "DBConnectionError appeared in logs",
    "database connection pool usage reached 98%"
  ],
  "recommended_actions": [
    "compare deployment v2.3.6 and v2.3.7",
    "check connection pool config",
    "prepare rollback if error rate remains high"
  ],
  "requires_approval": true
}
```

## 6. 第一阶段暂不加入

```text
Harness.io
LangGraph
CrewAI
Milvus
Kafka
Kubernetes
Grafana
OpenTelemetry
PostgreSQL
```

这些不是否定，而是先让最小链路可跑、可测、可解释。SQLite 可在 Trace/Incident 数据模型稳定后加入。
