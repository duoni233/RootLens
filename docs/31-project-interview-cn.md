# RootLens 面试突击手册

> 以当前代码为准整理。目标是让一个没听过项目的人先听懂业务，再顺着业务理解技术。可以适度突出工程亮点，但不要把模拟数据包装成生产系统。

## 1. 项目是什么

RootLens 是一个面向企业内部系统异常排查的多 Agent 智能诊断平台。用户提交服务名、故障时间和异常现象后，系统会查询日志、指标和发布记录，检索对应 Runbook，再让应用、数据库或基础设施 Agent 协同分析，最终输出一份区分**确认事实、待验证假设和处置建议**的结构化诊断。

项目还提供执行 Trace、故障降级测试、自动化评测、诊断历史和可视化工作台，用来回答：系统查到了什么、为什么这样路由、哪一步失败了、最终结论依据什么。

更短的版本：

> 我做的是一个多 Agent 故障诊断系统。它先根据服务和故障时间查询日志、指标、发布记录，再结合 Runbook 做证据增强分析，把请求交给应用、数据库或基础设施 Agent。最终输出带证据引用的结构化诊断，并支持评测、Trace 和历史回看。

一句话版本：

> RootLens 把“让大模型猜故障原因”改成了“先查证据，再做诊断”。

面试开场先用上面两段，不需要介绍项目来源，也不要一上来报 Redis、ChromaDB、Pydantic 等技术名词。

## 2. 业务场景

RootLens 面向内部应用服务、数据库和基础设施故障。用户可能遇到：

- 服务 5xx 激增、接口报错、超时或不可用；
- 发布新版本后出现异常，需要判断二者是否相关；
- 数据库连接池耗尽、慢查询、锁等待或连接错误；
- CPU、内存、节点、网关、DNS 等资源或网络异常；
- 只想查询某类故障的 Runbook；
- 信息不完整，需要系统先追问服务名或故障时间。

最适合演示的一条请求是：

```text
payment-service 从 10:05 开始 5xx 激增，刚发布 v2.3.7，帮我判断原因。
```

这条请求看似简单，其实包含三个问题：

1. 10:05 附近现场发生了什么；
2. 10:00 的发布是否与异常相关；
3. 应用层和数据库层是否需要一起分析。

系统会向前查询发布记录，查询故障前后的日志和指标。当前模拟数据中能找到 5xx 上升、连接池达到上限和数据库连接获取超时，因此 ApplicationAgent 负责主诊断，DatabaseAgent 提供辅助分析。但系统不会因为“10:00 发布、10:05 故障”就断言发布是根因，而会把“版本可能引入连接泄漏或配置变化”列为待验证假设。

这就是项目最重要的业务原则：

```text
现场 Evidence = 本次查到的事实
Runbook         = 通用处置知识
Hypothesis      = 仍需验证的原因
```

三者不能混在一起。

## 3. 技术栈

| 层次 | 当前使用 | 主要作用 |
| --- | --- | --- |
| 后端 API | Python、FastAPI、Pydantic | 异步接口、请求响应模型、结构化校验、Swagger |
| 大模型调用 | Anthropic SDK 兼容接口 | 意图识别、Agent 分析、查询改写、重排、结构化组装、Judge |
| 多 Agent | 自定义 AgentOrchestrator | 主辅 Agent 路由、并行执行、失败降级 |
| 工具治理 | 自定义 MCPToolManager | 参数校验、TTL 缓存、超时、熔断、fallback、统计 |
| RAG | ChromaDB、Query Rewrite、Multi-query、Rerank | Runbook 向量召回和候选精排 |
| 会话记忆 | Redis | 当前会话消息、摘要、24 小时 TTL |
| 诊断历史 | SQLAlchemy、SQLite | 保存 DiagnosisRun、结构化诊断和 Trace 快照 |
| 前端 | React、TypeScript、Vite、React Router | 新建诊断、补充信息、历史、Trace 展示 |
| 部署与监控 | Docker Compose、Nginx、Prometheus | 服务编排、反向代理、健康检查和指标暴露 |
| 测试评测 | pytest、Vitest、确定性指标、LLM-as-Judge | 回归、故障注入、诊断质量辅助评估 |

技术栈表是面试官追问时用的，不要拿它代替项目介绍。

## 4. 一次请求的完整链路

一次 `/chat` 请求会经过：

```text
用户请求
  -> Redis 读取当前会话上下文
  -> Intent 识别 + RootLens 实体投影
  -> Evidence Gate：判断是否需要现场取证
  -> QueryContext：确定服务、环境、事件时间和查询窗口
  -> 并行查询 logs / metrics / deployments
  -> EvidenceBundle：汇总证据和每个工具的状态
  -> 用有来源的 Evidence 关键词增强 Runbook 检索
  -> 根据意图、关键词、实体和 Evidence 生成领域分数
  -> 选择 Primary Agent 和 Supporting Agents
  -> 单 Agent 或主辅 Agent 并行执行
  -> DiagnosisAssembler 生成 IncidentDiagnosis
  -> Validator 校验证据引用和动作风险
  -> 记录 DiagnosisTrace
  -> 写回 Redis，会话外再保存 SQLite 历史
  -> 返回 Markdown、结构化诊断、路由和工具状态
```

主要模块分工：

| 模块 | 职责 |
| --- | --- |
| `core/diagnosis_entry.py` | `/chat` 与评测共用的意图识别和诊断入口 |
| `core/intent_recognizer.py` | 意图、实体、紧急度和来源分数 |
| `core/evidence.py` | QueryContext、时间窗口、Evidence 契约和 Bundle |
| `mcp/incident_tools.py` | 模拟日志、指标、发布记录查询 |
| `core/diagnosis_pipeline.py` | 取证、RAG、路由和结构化诊断的主流程 |
| `agents/agent_orchestrator.py` | 主辅 Agent 选择、并行执行与 GeneralOps 降级 |
| `mcp/tool_manager.py` | 工具缓存、超时、熔断、fallback、改写和重排 |
| `mcp/knowledge_base.py` | RootLens ChromaDB 知识库 |
| `core/incident_diagnosis.py` | 结构化诊断契约 |
| `core/diagnosis_trace.py` | 一次诊断的步骤、耗时和状态 |
| `evaluation/rootlens_evaluator.py` | 使用同一诊断主链执行评测 |
| `persistence/` | SQLite 历史保存和查询 |
| `frontend/` | 诊断工作台、历史详情和 Trace 页面 |

## 5. 多 Agent 怎么设计

### 5.1 Agent 分工

```text
AgentOrchestrator
  ├── GeneralOpsAgent       信息澄清、告警分诊、跨领域总结
  ├── ApplicationAgent      5xx、接口错误、超时、版本发布
  ├── DatabaseAgent         连接池、慢查询、锁等待、事务异常
  └── InfrastructureAgent   CPU、内存、磁盘、网络、网关、DNS
```

人工升级目前是一个状态和路由结果，不是已经接入真实工单平台的独立执行系统。

Agent 的区别主要来自领域角色、路由条件和动态 Skills。当前四类 Agent 使用同一个模型客户端；不要包装成“每个 Agent 都使用不同模型、不同工具白名单”，因为实际现场工具由 Pipeline 统一调用。

### 5.2 为什么不是一个大 Agent

单 Agent 也能回答，但领域职责容易混在一起。主辅模式让系统明确“谁负责最终判断、谁补充专业视角”，也让路由和失败状态更容易观察和评测。

例如 payment-service 案例：

```text
primary_agent    = application
supporting_agent = database
```

两个 Agent 并行分析同一份现场证据。当前实现不是 Agent 之间互相对话，也不是 DatabaseAgent 把中间结果再交给 ApplicationAgent；它属于“主辅并行分析”。自然语言结果先按主处理/辅助处理顺序组合，再由 DiagnosisAssembler 组织为统一结构化诊断。

面试时可以这样说：

> 我没有让 Agent 自由决定无限循环和随意调用工具，而是由 Pipeline 先完成受控取证，再只做一次最终路由。这样工具范围、时延、失败状态和评测路径都比较清楚。

### 5.3 主辅 Agent 怎么选

路由分数来自四部分：

- Intent 对某个领域的基础分；
- 用户消息中的领域关键词；
- 结构化实体，例如 `DBConnectionError`；
- 现场 Evidence 提供的领域分数下限。

现场证据采用 `max(原分数, evidence floor)` 合并，同类重复日志不会一直累加。最高分是主 Agent；其他领域分数至少达到 `0.45`，且达到主分数一定比例时，才作为辅助 Agent。

这些分数表示启发式领域相关度，不是“数据库是根因的概率”。

### 5.4 Agent 失败怎么办

专业 Agent 返回失败时，Orchestrator 可以降级到 GeneralOpsAgent；主 Agent 与辅助 Agent 的执行记录分别保留。辅助 Agent 失败时，主 Agent 的可用结果仍然可以返回，并把整体标为 degraded。

## 6. Intent 和实体识别

RootLens 主要意图包括：

```text
service_incident   服务异常本身
latency_issue      延迟、超时
deployment_issue   调查发布/版本/变更与异常的关系
database_issue     数据库与连接池问题
resource_issue     CPU、内存、磁盘等资源问题
network_issue      网关、DNS、502/503 等网络问题
runbook_query      查询排障手册
alert_triage       告警初步分诊
human_handoff      请求人工介入
unknown            无法判断
```

最容易被追问的是 `service_incident` 和 `deployment_issue` 的边界：

- “payment-service 5xx 激增”主要调查服务异常，属于 `service_incident`；
- “发布 v2.3.7 后开始 5xx，帮我判断是否相关”把发布作为调查焦点，属于 `deployment_issue`；
- “不确定是否与发布有关”但主要仍在排查服务异常，优先 `service_incident`。

分类意图并不等于认定根因。

### 6.1 当前识别路径

代码支持 LLM、Pattern 和可选 Embedding 三路。但当前第三方兼容模型配置存在 `base_url`，Embedding 路径默认关闭，因此真实部署主要是：

```text
LLM 语义识别  0.85
Pattern 规则   0.15
```

LLM 负责上下文和复杂表达，Pattern 负责 `5xx`、`DBConnectionError`、`CPU`、`Runbook` 等强特征以及 LLM 失败后的兜底。代码中保留的本地字符 n-gram 只能称为轻量相似度 fallback，不能说成成熟中文语义 Embedding。

为什么不只用 LLM：

> LLM 擅长复杂语义，但 API 可能失败或输出异常。规则对错误码和高风险强特征更确定，也更容易解释。是否继续保留某一路，应由评测结果决定，而不是为了凑“多路融合”。

### 6.2 实体为什么用规则抽取

当前高价值实体包括：

```text
date / service_name / start_time / version / status_code / error_code
```

这些格式相对稳定，用正则抽取比每次再调用一次 LLM 更快、更便宜、更可测试。RootLens 在进入 Pipeline 前还做实体白名单投影，过滤旧业务字段和空值，避免无关实体进入路由和 Prompt。

## 7. Evidence：现场取证层

这是 RootLens 区别于普通聊天机器人的关键模块。

### 7.1 QueryContext

取证前必须明确：

```text
service_name + environment + anchor_time + timezone + dataset_version
```

默认策略中，日志和指标查询故障前 5 分钟到后 15 分钟；发布记录向前回看 60 分钟。这样用户说 10:05 出现故障时，系统能查到 10:00 的发布。

缺少服务或关键时间时，系统先澄清，不进行全库扫描，也不凭空猜日期。demo 中允许使用明确标注的固定模拟日期，生产场景不能沿用这个假设。

### 7.2 三个工具

```text
query_logs
query_metrics
query_deployments
```

三个查询互不依赖，通过 `asyncio.gather` 并发执行。并发的价值是重叠 I/O 等待，不是让 CPU 计算自动变快。

工具沿用 ToolManager 的参数 Schema、5 秒超时、30 秒 TTL 缓存、熔断状态和统计。每条 Evidence 都有稳定 ID，例如：

```text
rootlens-demo:v2:INC-001:log:L001
```

稳定 ID 用于去重、结构化引用、Trace 和评测；`retrieved_at` 可以变化，源记录身份不能随请求变化。

### 7.3 四种工具状态

```text
ok        查询成功且有记录
empty     查询成功但没有记录
failed    查询本身失败
degraded  fallback 或部分结果可用
```

`empty` 不能当成失败，`failed` 也不能伪装成“现场没有异常”。fallback 的说明文字不能进入 Evidence，否则模型会把系统提示误当成事实。

### 7.4 为什么第一版使用模拟数据

真实日志平台、Prometheus 和发布系统需要权限、接口和脱敏数据。第一版先用内部一致的版本化 JSON，保证同一故障的日志、指标和发布记录互相对应，也能稳定复现测试。

面试时应说：

> 我实现的是可替换的数据契约和查询工具，当前 provider 是模拟数据。接入真实 ELK、Prometheus 或发布平台时，主要替换 handler，Evidence 契约和后续诊断链保持不变。

不能说已经接入生产日志或真实 Prometheus 数据。

## 8. RAG：Runbook 检索

RootLens 使用独立的 ChromaDB collection：`rootlens_runbooks_v1`。知识包括连接池耗尽、应用 5xx、发布排查 Runbook 和一条历史事故材料，与旧业务知识隔离。

检索链路是：

```text
原始问题
  -> 加入有 Evidence ID 支持的错误词
  -> Query Rewrite：原问题 + 多角度子查询
  -> ChromaDB 并行召回
  -> 按 chunk_id 合并去重
  -> LLM Rerank
  -> Top-K Runbook 注入 Agent 上下文
```

例如用户只说 5xx，但日志 Evidence 查到 `DBConnectionError` 和 `connection pool exhausted`，这些词可以增强检索，更容易命中连接池 Runbook。没有现场来源支持的模型猜测不能加入 query，用户原始消息也不会被覆盖。

### 8.1 Rewrite、召回和 Rerank 的关系

- Rewrite 从不同角度生成检索表达，提高召回机会；
- ChromaDB 从全量文档中找候选；
- Rerank 只对少量候选做更细的相关性排序。

如果召回阶段没找到相关文档，Rerank 无法凭空补回来。

### 8.2 RAG 状态必须真实

每个阶段记录 `performed / skipped / failed / degraded`。改写失败时退回原始 query，重排失败时保留原顺序；失败不能写成 performed。知识库 fallback 文本存在也不能宣称“命中了 Runbook”。

当前仍存在额外 Runbook 命中噪声，因此不能编造 Recall@K 提升数字。更准确的说法是：项目实现了可观察的改写、召回、去重和重排链，并通过固定案例检查目标 Runbook 是否命中。

### 8.3 RAG 和 Skills 的区别

```text
RAG     查“有哪些相关知识或处置文档”
Skills 约束“这个 Agent 应按什么规则处理”
```

Runbook 是检索结果，不能直接当作本次现场事实；Skill 更像随请求注入的业务规则和安全边界。

## 9. 动态 Skills

当前有四份领域 Skill：应用故障、数据库故障、基础设施故障和运维分诊。Skill 文件带有：

```text
name / description / keywords / agents / enabled / content
```

SkillManager 先按 Agent 白名单过滤，再按关键词匹配，把命中的规则注入对应 Agent 的 system prompt。Evidence 中抽取的错误码也会参与关键词匹配。例如 `DBConnectionError` 可以让 DatabaseAgent 命中数据库诊断规则。

优点是低延迟、可解释、可热加载；不足是口语化表达和同义词覆盖有限。目前不是完整的语义 Skills 检索，面试时不要说已经实现向量化 Skills 路由。

热加载接口：

```text
GET  /skills
POST /skills/reload
```

总注入长度有限制，避免所有规则同时塞进 Prompt。

## 10. Memory 怎么讲

当前 RootLens 主要保留 Redis 工作记忆：保存当前会话最近消息和摘要，TTL 为 24 小时。消息超过阈值时，系统让模型生成摘要；只有摘要成功且会话没有并发变化时，才通过 Redis 事务提交摘要并裁剪旧消息。

代码还保留 ChromaDB episodic 和 user_profile 能力，但 RootLens 默认：

```text
user_profile 读取/更新关闭
跨会话 episodic 自动召回关闭
```

原因是客服“用户画像”不能机械改名成服务画像，其他历史会话也不应在没有来源边界的情况下污染当前故障诊断。当前会话 Redis 仍正常工作，压缩后的 episodic 可以存档，但默认不自动注入其他会话内容。

如果面试官问为什么不用一个数据库保存所有东西：

> Redis 适合低延迟、带 TTL 的会话状态；ChromaDB 负责语义检索；SQLite 负责可分页查询的诊断历史。它们的访问模式不同，强行混用会让职责和一致性边界更模糊。

## 11. 结构化诊断

Agent 的 Markdown 可读，但其他系统很难稳定消费。RootLens 因此增加 `IncidentDiagnosis v1`：

```text
status                    diagnosis / runbook / clarification
summary
affected_services
primary_agent / supporting_agents
confirmed_findings        必须引用 Evidence ID
hypotheses                假设 + 验证步骤
recommended_actions       动作、原因、风险、是否审批
evidence_gaps             还缺什么、为什么需要
evidence_refs / knowledge_refs
tool_status
degraded / requires_approval
```

DiagnosisAssembler 使用模型把 Agent 结果和来源整理为 JSON，Pydantic 再做严格校验：

- 额外字段被拒绝；
- unknown Evidence/Knowledge ID 被拒绝；
- high-risk 动作必须 `requires_approval=true`；
- clarification 不能夹带现场事实或工具输出；
- Runbook 问答不能伪造本次确认事实。

如果解析或校验失败，`diagnosis=null` 并给出明确构建状态，原始 Markdown 仍保留。这个策略叫 fail closed：宁可没有结构化对象，也不把不合法对象返回给下游。

需要主动承认：引用 ID 合法不代表文字一定被证据语义支持，因此项目还有人工来源审查和专门的 partial-evidence 回归案例。

## 12. Trace、降级和故障注入

### 12.1 DiagnosisTrace

Trace 记录：

```text
Intent Recognition
Evidence Gate / QueryContext
query_logs / query_metrics / query_deployments
RAG rewrite / retrieval / rerank
Routing
每个 Agent execution
Diagnosis assembly
```

每一步记录开始/结束时间、耗时、状态、错误码、Evidence ID 和 Knowledge ID。状态分为：

```text
success / failed / degraded / skipped
```

空结果用 `success + empty` 表示，不写成失败。UTC 时间用于对齐和展示，`time.monotonic_ns()` 用于计算耗时，避免系统时钟调整影响时长。

Trace 只记录 allowlist 元数据，不保存 Prompt、Authorization、模型隐藏推理、完整异常堆栈或 Agent 全文。

要如实说明：这是诊断核心链的 Trace，不包含 `/chat` 前后的完整 Redis 和 HTTP 生命周期，不是 OpenTelemetry 分布式追踪。

### 12.2 Failure Injection

故障注入只存在测试目录，不通过 `/chat?fail=...` 暴露。测试场景包括：

- 日志工具超时、指标工具异常、工具空结果；
- RAG 改写或检索失败；
- Supporting Agent 失败、Primary Agent 降级；
- Assembler 坏 JSON、API 异常、引用未知 ID；
- 正常路径和澄清路径。

验证目标不是“任何故障都能恢复”，而是：Trace 是否如实记录，失败是否被隔离，可用证据和 Markdown 是否还能保留，结构化对象是否拒绝非法来源。

## 13. 自动化评测

最重要的评测设计是：`/eval/run` 和 `/chat` 复用同一个 `run_diagnosis()` 核心入口，不能线上一条链、评测另一条链。

评测数据分为两部分：

```text
runtime   模拟日志、指标、发布记录，系统运行时可读
expected  意图、路由、证据、Runbook、禁止结论，只在运行结束后由 Evaluator 读取
```

这样避免把标准答案泄漏给 Agent、RAG 或工具。

当前六案例包含四组故障、一个 Runbook 问答和一个信息不足澄清。确定性指标包括：

- Intent Accuracy / Macro-F1；
- Primary Agent Accuracy；
- Supporting Agent Exact / Partial Match；
- Evidence Coverage；
- Tool Status Accuracy；
- Clarification Accuracy；
- Runbook Hit Accuracy；
- Forbidden Claim Violation Count。

每项指标都保存 numerator、denominator 和 value；不适用案例不进入分母，空分母返回 null，不伪造满分。

### 13.1 LLM-as-Judge

Judge 从四个维度辅助评估自然语言回答：

```text
evidence_grounding
diagnostic_reasoning
actionability
safety_and_uncertainty
```

它区分 diagnosis、runbook、clarification 三种模式。例如澄清场景不因“没有猜根因”被扣分。Judge 输出 JSON 必须通过 Schema 校验；JSON 错误、截断或 API 失败时标记 invalid，不填默认 0.5。

### 13.2 Baseline 和回归

Baseline 带 suite version、dataset version、schema version、模型/provider、case IDs 和 fingerprint。只有兼容版本才能比较，promotion 需要人工显式批准，不自动覆盖历史快照。

当前保存的真实六案例验收为结构化诊断 6/6、Judge v2 有效 6/6，但这只是合成回归集，不等于生产准确率 100%。

## 14. 历史、API 和前端

### 14.1 DiagnosisRun

`IncidentDiagnosis` 表示诊断出了什么，`DiagnosisTrace` 表示过程怎么运行；`DiagnosisRun` 把两者归为同一次诊断，并保存原问题、服务、意图、Agent、Markdown、结构化快照和来源引用。

SQLite 通过 SQLAlchemy Repository 访问。普通 `/chat` 完成后才尝试保存；评测运行不写普通历史。数据库失败时，诊断回答仍返回，`persistence_status=failed`，不会因为写历史失败把主请求拖垮。

历史 API 支持列表、筛选、详情和独立 Trace 查询。共享 token 只适合本地私有演示，不是用户级权限、TLS 或租户隔离。

### 14.2 React 工作台

控制台支持：

- 提交新诊断并在同页补充澄清信息；
- 分开展示确认事实、假设、建议、证据缺口和工具状态；
- 按服务、状态、降级和待补充信息筛选历史；
- 查看结构化详情和 Trace 时间线；
- 从历史进入“解读已有记录”或“重新诊断”。

两个入口必须分开：

- 解读已有记录：只解释归档结构化诊断，不重新查现场；
- 重新诊断：创建新 `/chat` 请求，重新获取 demo Evidence，不把旧结论当作事实继承。

这是一次真实 bad case 修复：旧版本把解释问题拼进新诊断，导致 QueryContext 因时间歧义继续追问。拆成两个模式后，语义边界才正确。

## 15. 部署方式

Docker Compose 运行五个服务：

```text
rootlens-app
rootlens-redis
rootlens-chromadb
rootlens-prometheus
rootlens-nginx
```

Nginx 同源提供前端静态文件并反向代理 API，减少跨域配置。SQLite 使用独立 volume，容器重建后历史仍能读回。各服务配置 healthcheck 和 `depends_on` 健康条件。

当前前端先在宿主机执行 Vite build，再由 Nginx 只读挂载 `dist`。这是一套本地可复现部署，不是 Kubernetes、高可用集群或生产发布流水线。

## 16. 当前验证结果

项目不是只用一条演示请求截图，而是保留了分层验收证据：

- 最新记录的后端隔离回归为 322/322，前端 Vitest 为 22/22；
- 固定六案例真实模型评测中，结构化诊断 6/6 构建成功，Judge v2 6/6 返回有效结果；
- Stage 5 的 Trace / Reliability 回归覆盖正常、澄清和受控失败路径；
- SQLite 历史在应用重启和镜像重建后仍可读；
- 五个 Compose 服务曾完成 healthy 验收；
- 一条真实模型的历史解读 API 冒烟测试能区分事实、假设和行动，没有把发布时间相近写成确定根因。

这些数字只能证明当前代码在固定合成数据和受控环境中通过回归。Stage 7 的浏览器“解读已有记录 / 重新诊断”双模式仍待 Owner 最终确认；项目也没有生产负载、真实外部平台故障或大规模人工标注集的验证。

## 17. 项目中最值得讲的四个问题

### 17.1 评测绕过真实主链

现象：早期 `/eval/run` 直接调用旧 Orchestrator，没有经过 Evidence 和新 RAG，因此分数不能代表 `/chat`。

解决：抽出 `run_diagnosis()`，让 API 和 Evaluator 共用。Evaluator 只先取运行输入，等所有运行结束后才读取 expected 计算指标。

验证：测试 expected 不进入 Tool 参数、Prompt、RAG 或 Memory；真实六案例从同一核心链产生 Observation。

### 17.2 模型输出 JSON 不稳定

现象：结构化 Assembler 曾出现截断、坏 JSON 和未知引用。

解决：限制输出格式和预算，用 Pydantic 严格校验并 fail closed；失败时保留 Markdown，不返回半合法对象。

复盘：Schema 能保证结构和引用存在，但不能证明每句话都被证据语义支持。

### 17.3 部分证据被错误归因

现象：某个案例只有 5xx 指标，没有日志，但生成结果把“日志为空”与指标 ID 混成确认事实。

解决：修正模拟源记录的来源边界，强化事实必须引用对应 Evidence 类型，并增加人工来源审查和回归案例。

这个问题说明：有 Evidence ID 不代表引用就一定正确，必须检查 claim-evidence 对应关系。

### 17.4 历史追问进入了错误流程

现象：用户只是想问“哪些是事实，哪些是假设”，系统却把旧问题、摘要和追问重新送入故障诊断，因多个时间继续要求补充信息。

解决：区分只读历史解读和重新诊断。前者不调用 Intent、现场工具、RAG 或 Memory；后者使用新会话重新取证。

面试讲问题时用：**现象 -> 定位 -> 改动 -> 验证 -> 仍有边界**。

## 18. 为什么没有使用这些技术

### LangGraph / CrewAI

当前链路明确，已有自定义 Orchestrator 和 ToolManager。为了一个可控工作流迁移框架，会增加状态映射和回归成本。未来若出现多轮 Agent 依赖、可暂停恢复的长任务，再考虑图式编排。

### Milvus

当前只有少量 Runbook，ChromaDB 足够完成 collection 隔离和语义检索。Milvus 更适合更大规模、分布式向量检索场景，当前引入只会增加运维成本。

### PostgreSQL

SQLite 能验证 Schema、Repository、快照版本、分页和重启持久化。当前是本地单机演示，没有多实例并发写和复杂事务需求；进入多用户部署后再迁移 PostgreSQL，并补 Alembic。

### Kafka

目前一次诊断是同步请求链，没有高吞吐事件流、跨服务消费或重放需求。为简历堆一个消息队列没有实际价值。

### Kubernetes

当前只验证本地五服务编排，Docker Compose 更容易复现。Kubernetes 应在出现真实弹性、滚动发布和多副本需求后使用。

### OpenTelemetry / Grafana

当前自定义 Trace 能验证诊断步骤和故障降级，但不是生产级分布式可观测性。真实多服务部署后，应将 Trace、Metrics、Logs 接到 OpenTelemetry 和可视化平台。

## 19. 高频追问短答

1. **为什么先查证据再路由？** 用户描述可能只说 5xx，日志却能暴露数据库连接错误。先统一取证可以让主辅路由基于事实，同时避免第一版做两次路由。
2. **Runbook 能作为现场事实吗？** 不能。它是通用知识，只能提供排查方法；本次故障事实必须来自 Operational Evidence。
3. **为什么发布记录不能直接证明根因？** 时间相关不等于因果，还需版本差异、连接生命周期、数据库和流量对照。
4. **为什么不让 Agent 自己随意调工具？** 集中取证便于限制时间范围、统一状态、控制成本、记录 Trace 和复用评测。未来工具规模大时可增加 pre-route 或受控 Tool Loop。
5. **`asyncio.gather` 有什么用？** 重叠三个独立 I/O 查询的等待时间；它不让 CPU 密集任务自动并行。
6. **缓存有什么一致性问题？** knowledge search 使用 300 秒 TTL，知识更新后 TTL 内可能读旧结果，属于最终一致；可通过写后失效、版本号或共享 Redis 缓存改进。
7. **熔断器解决什么？** 连续失败时快速拒绝调用，避免反复等待已经不健康的依赖；还需要 half-open 恢复策略和真实故障验证，不能只说“有熔断就高可用”。
8. **Pydantic 能防止幻觉吗？** 不能。它能检查结构、类型、未知引用和审批规则，但语义真实性仍需要 Evidence 对照、Judge 和人工审查。
9. **为什么评测答案要隔离？** 如果 expected 被 Agent 或 RAG 读到，就是答案泄漏，指标失去意义。
10. **为什么 Judge 不能代替人工？** Judge 也可能偏置或输出无效 JSON；项目只统计 valid case，并保留人工审查和确定性指标。
11. **Trace 为什么用 UTC 和 monotonic 两种时间？** UTC 用于事件对齐，monotonic 用于可靠计算耗时，不受系统时钟跳变影响。
12. **六案例 6/6 是不是准确率 100%？** 不是。它只说明固定合成回归集通过，不能推断真实故障分布上的表现。
13. **为什么 Redis、ChromaDB、SQLite 都要用？** 分别对应短期会话、向量检索和可查询历史，访问模式不同。
14. **共享历史 token 安全吗？** 只适合本地私有演示；没有用户身份、角色、租户和 TLS，不能作为生产鉴权。
15. **这算多 Agent 吗？** 算主辅 Agent 并行协作，但不是 Agent 之间自主多轮通信，也不是复杂串行依赖工作流。

## 20. 面试表达边界

可以说：

- 做了基于证据的多 Agent 故障诊断链；
- 实现了模拟 logs/metrics/deployments 工具和可替换契约；
- 让线上入口与评测入口复用同一核心流程；
- 实现结构化诊断、Trace、受控故障测试、历史和前端；
- 通过固定合成案例、真实模型调用和自动化回归验证。

不要说：

- 已接入真实生产日志、Prometheus 或发布平台；
- 六案例证明生产准确率 100%；
- 已实现标准 MCP Server、完整 Agent 自主 Tool Loop；
- 已实现生产级鉴权、Human-in-the-loop 回滚、Kubernetes 高可用；
- 整个 Agent Runtime 完全从零原创。

如果面试官追问项目来源，可以如实回答：

> 我基于一个已有的多 Agent 运行时做了业务重构，复用了基础编排和工具管理思路。我的重点工作是重新设计故障领域模型、证据工具与数据、RootLens 知识隔离、证据增强路由、结构化诊断、评测对齐、Trace/故障测试、历史持久化和前端工作台，并按阶段做了回归和真实模型验收。

这句话放在被问到“是否从零开发”时回答，不需要放在项目开场。

## 21. 学习顺序

不要一次背完整文档。建议按以下顺序：

1. 先能说清第 1、2、4 节：项目、例子和完整链路；
2. 再掌握第 5、7、8、11 节：Agent、Evidence、RAG、结构化诊断；
3. 然后学习第 12、13 节：Trace、降级和评测；
4. 最后练第 17、18、19 节：真实问题、技术取舍和高频追问；
5. 每讲一块，都回到对应源码和验收文档看一次，避免只会背结论。

真正需要形成的能力不是记住所有函数参数，而是能回答五件事：**为什么做、请求怎么走、你改了什么、怎么验证、还缺什么。**
