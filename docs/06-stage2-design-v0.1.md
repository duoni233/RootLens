# RootLens Stage 2 Design v0.1

日期：2026-09-28；评审通过：2026-09-29。状态：第 1、2 批独立能力已实现并测试，主链衔接与部署仍为计划。

目标：Evidence Acquisition + Evidence-aware Routing，即先取得现场事实，再完成一次主辅 Agent 路由。

基线：第一阶段核心验收见 `05-first-stage-acceptance.md`，Git 基线 `ebe3761`。第一阶段证明意图、实体、主辅路由、Skills 和真实 Agent 调用可工作，不代表 RAG、画像或完整故障诊断已经验收。

初次设计审计只增加本设计文档。2026-09-29 按批准范围实施第 1 批，详情见 `07-stage2-batch1-acceptance.md`。现有用户文件 `chatgpt聊天结果.md` 保持原样。

评审补充约束：现场 Evidence 与知识 Evidence 必须显式分类；事件时间 observed_at 与取证时间 retrieved_at 分开；共用管线只编排，不承载 loader/时间规则；Stage 2 不优化根因准确率。本批 Evidence 只接受 operational 的 log/metric/deployment，knowledge 仅保留类别定义，尚未实现知识证据。

## 1. 当前 /chat 调用链：源码事实

```text
api/main.py: chat
  -> MemoryManager.get_context：最近消息、历史摘要、用户画像、会话摘要
  -> AgentOrchestrator.recognize_intent：单主意图、实体、置信度
  -> _build_knowledge_context：原始问题 -> knowledge_search
  -> Request：记忆 + 知识文本 + 用户实体 + 意图
  -> AgentOrchestrator.run
      -> 澄清检查
      -> _route_decision -> _domain_scores
      -> 一个主 Agent、可选辅助 Agent
      -> Skills + 上下文 -> LLM 回复
  -> Redis 写入用户消息和回复
  -> 后台 update_profile
  -> ChatResponse
```

源码入口：

| 文件 / 函数 | 当前事实 |
| --- | --- |
| `app/api/main.py: chat` | 意图识别后先检索，再运行 Orchestrator；没有现场取证 |
| `app/agents/agent_orchestrator.py: Request` | 没有 Evidence 或 routing_signals 字段 |
| `app/agents/agent_orchestrator.py: _domain_scores` | 按用户意图、原文关键词、用户实体独立打领域分；不读取工具证据 |
| `app/mcp/tool_manager.py: call` | 已有缓存、熔断、校验、超时、降级，可承载新工具 |
| `app/mcp/tool_manager.py: _fallback_result` | 降级成功可能同时 `success=True` 且 `error` 非空；不能把它当正常取证 |
| `app/mcp/knowledge_base.py` | 默认 knowledge_base 集合，会向空集合写入旧客服文档；查询未返回稳定文档 ID |
| `app/memory/conversation_memory.py` | 画像仍是客服偏好；历史摘要按 user_id 检索，不保证属于当前服务/故障 |
| `app/evaluation/evaluator.py: _evaluate_dialog_case` | 直接 `orchestrator.run`，绕过 API 的记忆和 RAG，也会绕过未来取证入口 |

还有两个已知边界：第三方模型配置下 Embedding 未运行，不能宣称三路同时识别；RAG 改写/重排仍有 JSON 解析失败，`search_with_rewrite` 的 reranked 标记也不能证明真的执行成功。

## 2. Stage 2 目标调用链

```text
用户输入 + 可选环境/完整时间
  -> 读取当前会话记忆
  -> Intent + Entity（保留单主意图契约）
  -> Evidence Required?
      否：问候/澄清/Runbook 查询路径
      是：Build QueryContext，缺关键条件则澄清
           -> 并行 query_logs / query_metrics / query_deployments
           -> 校验、归一化 -> EvidenceBundle
           -> 仅从现场 Evidence 提取 routing_signals
  -> 原问题 + 有来源的线索 -> RAG 查询
  -> Request：原问题、原实体、证据、规则知识、routing_signals
  -> Orchestrator.run -> 一次最终 _route_decision
  -> 主辅 Agent + Skills -> 区分事实/假设的诊断回复
  -> Memory Write -> ChatResponse
```

不做预路由或二次路由，不覆盖用户原意图，不把整段工具输出拼进 message 后重新识别。

Gate 第一版：service_incident、latency_issue、deployment_issue、database_issue、resource_issue、network_issue 需要现场证据；alert_triage 仅在存在具体服务和事件信息时取证。runbook_query、greeting、unknown/other 不自动查三个工具。Gate 是取证条件，不是另一套 Agent Router。

案例：输入只说“payment-service 从 10:05 开始 5xx 激增”，也应能通过工具发现 DBConnectionError，从而支持 DatabaseAgent；不能依赖用户自己把全部答案线索写进输入。

## 3. Memory / RAG 保留、替换、禁用

| 能力 | Stage 2 决策 | 原因和约束 |
| --- | --- | --- |
| Redis 最近消息、会话写入 | 保留 | 支持用户补充条件；会话陈述不是独立工具证据 |
| 当前会话压缩 | 保留但做窄范围检查 | 摘要为空/失败时不得删旧消息；需验证当前厂商的非思考参数适用性 |
| Chroma episodic 存档 | 可保留存档，暂禁跨会话注入 | 当前只按用户检索，可能把另一故障的结论带入当前诊断 |
| user_profile 读取/异步更新 | RootLens 默认禁用 | 客服偏好不适用；暂不机械改名为 service_profile |
| service_profile / team_context | 本阶段不新增 | 等明确数据归属和真实用途后设计 |
| RAG 改写、召回、去重、重排 | 沿用流程，修必要兼容 | 解决已知解析失败、真实执行状态；不更换检索引擎 |
| 旧客服知识 | 不注入 RootLens 诊断 | 独立使用 rootlens_runbooks_v1 集合，原集合不删除 |
| Runbook、过往故障案例 | 新增小规模明确来源数据 | Runbook 是处置规则，不是当前故障证据；历史案例需早于当前事件且非当前答案副本 |

禁用需覆盖读与写，不只是停止 update_profile；通过显式配置/参数控制，保留旧接口兼容，不删除旧数据。具体配置名待实现时确定。

## 4. QueryContext 契约

用已有 Pydantic 定义对象，不引入新的框架。以下是拟定字段，不是已存在代码。

| 字段 | 类型 / 规则 |
| --- | --- |
| service_name | 非空字符串，第一版只接受一个已登记服务；多个服务先澄清 |
| environment | 明确环境，例如 demo/prod；模拟模式的默认 demo 必须可见 |
| anchor_time | 带时区的完整 datetime，不能只存 10:05 |
| timezone | IANA 时区名，例如 Asia/Shanghai |
| dataset_id / dataset_version | 由后端选择的模拟数据集及版本，不是根因标签 |
| logs_window / metrics_window / deployments_window | start/end 完整时间，集中计算，不散落于 handler |
| assumptions | 缺日期等情况下采用的显式演示假设 |

固定演示数据拟采用 2026-09-01、Asia/Shanghai。用户只说 10:05 时，仅在显式 demo 模式下可补这个日期，并在结果中声明；非 demo 请求应要求补完整时间。不得悄悄使用电脑当前日期。

默认窗口：日志/指标 `[anchor-5min, anchor+15min]`；发布 `[anchor-60min, anchor]`。都包含边界，按事件时间排序，限制条数；参数集中配置，可在测试里覆盖。

10:05 故障能查到 10:00 的发布。发布先于故障只是相关线索，不等于发布已经被证明是根因。

时间筛选优先级：本次显式请求 > 本次实体 > 当前会话已确认条件 > 显式 demo 默认。有冲突需澄清或明确标记，不能混用不同环境/服务数据。

## 5. Evidence / EvidenceBundle 契约

| Evidence 字段 | 约束 |
| --- | --- |
| evidence_id | 数据集内稳定唯一，如 demo-v1:INC-001:log:0003；同一源记录重复召回不换 ID |
| source_type | log / metric / deployment / runbook / historical_incident |
| service_name / environment | 用于范围校验，通用 Runbook 可显式标为 general |
| timestamp 或 time_range | 现场证据必须有完整时间；指标区间需完整起止 |
| summary | 简短展示文本，不能代替原始记录 |
| raw_ref | 可解析到允许目录中的源文件和记录 ID，不接受任意用户路径 |
| attributes | 按来源验证关键字段；不是无限制地相信任意字典 |

现场类型示例：日志含 error_code、message、severity；指标含 metric_name、value、unit、aggregation、interval；发布含 version、status、deployed_at。指标值必须有单位/聚合方法，错误率与错误次数不能混为一谈。

EvidenceBundle 包含 QueryContext、Evidence 列表、各工具状态（ok/empty/failed/degraded）、缺失来源和范围假设。空结果与工具失败必须分开。

同一类型的数据用同一结构表达；现场证据与 Runbook 在展示和上下文里分区。阶段 2 先允许回复引用 `[evidence_id]`，通过测试核验 ID 存在；引用格式本身不保证诊断正确。

拟定数据隔离：

```text
app/datasets/runtime/INC-001/{logs,metrics,deployments}.json
app/datasets/runtime/manifest.json
app/datasets/evaluation/INC-001.expected.json
app/knowledge/rootlens/                       # Runbook 和较早的历史案例
```

manifest 只含数据范围、时区、版本、服务登记，不含 expected_diagnosis/root_cause。运行态 loader 只读指定 runtime 根目录和白名单文件；不递归扫描 datasets 父目录。评测目录不挂载/复制进运行镜像，只有测试/Evaluator 使用。模拟数据需明确标注，不能包装成真实企业生产数据。

## 6. 三个工具 Input / Output

公共输入：service_name、environment、start_time、end_time、limit、dataset_version。上下文中的 dataset_id 由后端控制；日期范围和条数由 Pydantic 再校验，不能只依赖现有简化 JSON Schema 校验。

| 工具 | 可选过滤 | 输出 |
| --- | --- | --- |
| query_logs | severity / error_code | 时间范围内日志 Evidence 列表 |
| query_metrics | 允许的 metric_names | 范围内指标点/聚合 Evidence 列表 |
| query_deployments | version | 向前回看范围内发布 Evidence 列表 |

继续使用现有 `ToolResult`，`data` 存可序列化的 Evidence 列表，不替换成另一个不兼容返回类型。

- 正常无数据：success=True、data=[]、error=None，Bundle 状态 empty。
- 工具失败：success=False，不制造占位日志、指标或发布记录。
- 降级：必须标 degraded；不能只看 success=True 就认作现场事实。
- 初版新取证工具不提供虚构事实的 fallback；管线可以带部分证据继续，并报告缺失。
- 复用 call 的超时/缓存/熔断；缓存键包含所有筛选条件和数据集版本，避免换数据后命中旧记录。
- 固定三个调用只在 Gate 通过后并行执行；handler 内也校验服务、环境、时间范围，结果不得越界。

## 7. Evidence -> domain_scores 的接入位置

建议新增 `core/diagnosis_pipeline.py` 作为共享诊断入口：接收已识别意图、历史上下文和查询条件，负责取证、信号提取、RAG，最后调用 Orchestrator.run 一次。Memory 读写仍在 API 现有边界，不迁入 Router。

`Request` 增加默认空的 routing_signals/证据上下文；`_domain_scores` 保留原评分，在返回前合入证据领域信号；`_route_decision` 仍负责一次最终主辅选择。

第一版信号规则必须能解释：

| 现场证据 | 可用领域信号 | 不能推出的结论 |
| --- | --- | --- |
| 5xx 指标异常 | application | 唯一根因已确定 |
| 范围内 DBConnectionError / pool exhausted | database | 数据库服务必然宕机 |
| 故障前发布 | application | 必须立即回滚 |
| CPU/内存/节点资源异常 | infrastructure | 已排除应用或数据库因素 |

按不同信号种类去重，保留来源 ID，不按重复日志条数无限累加。初版采用领域下限合并 `max(原领域分, 证据领域下限)`，避免原文和工具重复出现同一错误码就双重加分。

例如数据库明确错误的下限可先设 0.55，满足现有辅助阈值；这是待测试的工程参数，不是统计置信度。保留原阈值，先通过样例/反例验证，不在此阶段做评分模型优化。

Runbook 的通用建议不能直接当成当前 domain 信号。只从范围内日志/指标/发布提取现场信号，不改写 IntentResult/entities 中的用户陈述；证据实体另存，保留来源。

## 8. RAG 的查询与范围

决定：取证后允许证据增强检索 query，但保留原问题，不改用户 message。

```text
原问题：payment-service 从 10:05 开始 5xx 激增
证据词：DBConnectionError、connection pool exhausted
检索 query：原问题 + service_name + 去重、有来源、长度受限的证据词
```

不加入 expected_diagnosis 或模型猜出的根因。没有有效证据时沿用原问题；runbook_query 直接检索，不查三个现场工具。

继续使用 knowledge_search 工具名和既有管理接口；RootLens 使用独立 rootlens_runbooks_v1 集合，初始化只导入 RootLens 文档，不自动加载客服种子。需要返回稳定 doc/chunk ID 与 source_ref，重复导入采用稳定 ID/upsert，不混进客服数据。

最小修正包括改写/重排的当前模型兼容参数、JSON 校验、performed/skipped/failed 状态。RAG 降级只能说明规则知识不可用，不能把通用 fallback 文本当成检索命中的 Runbook。文档质量、检索提升幅度仍需后续数据评测，不预先承诺。

## 9. 最小文件修改清单与执行顺序

以下为拟定范围，不是本次已修改清单。实现前逐批确认。

| 文件 | 拟定改动 |
| --- | --- |
| 新增 `app/core/evidence.py` | QueryContext、Evidence、Bundle、窗口规则、确定性信号提取 |
| 新增 `app/mcp/incident_tools.py` | 模拟 runtime loader、三个查询 handler，无真实生产操作 |
| 新增 `app/core/diagnosis_pipeline.py` | Gate、取证、知识检索、组装 Request、一次执行 |
| `app/api/main.py` | 注册工具、调用共用入口、增加可选查询条件/证据返回，旧响应字段保留 |
| `app/agents/agent_orchestrator.py` | Request 新字段、评分合入证据信号、Agent 上下文呈现证据 |
| `app/mcp/knowledge_base.py` | 可配置集合/初始化、RootLens 文档和来源 ID |
| `app/mcp/tool_manager.py` | 必要的模型兼容和真实重排状态，不重写缓存/熔断框架 |
| `app/memory/conversation_memory.py` | 禁用画像与跨会话注入的显式开关；压缩失败保护 |
| 数据、测试、部署配置 | 少量一致的模拟数据与 Runbook、确定性测试；仅 runtime/知识路径进入镜像 |

`evaluation/evaluator.py` 不在第一批重写。之后通过小型适配接入共用管线；接入前 `/eval/run` 不能代表完整 Stage 2 取证验收，先用管线测试和真实 HTTP 验收。不能因为 HTTP 200 就宣称评测已覆盖新链路。

实施分批：

1. 契约 + 一组数据 + 三个工具确定性测试；不连接 LLM，不改路由。
2. 最小记忆隔离、RootLens 知识集合和必要 RAG 兼容测试。
3. 共用管线、证据信号、一次路由、API 衔接；保留第一阶段回归用例。
4. Docker 构建与真实 /chat 验收；失败停在具体层，不顺手扩大范围。

每批记录“原来做什么、为什么改、怎样验证”，测通过后再提交作为回退点。修改前检查现有用户变更，不覆盖注释或其他未提交文件。

本阶段不加 Trace、SQLite/PostgreSQL、前端、OpenTelemetry、Grafana、Failure Injection 平台、自动回滚、Agent 框架。模拟一次工具异常的测试不等于建设故障注入平台。所需能力优先沿用现有 Pydantic、asyncio、pytest、Redis、ChromaDB、Docker，无需新服务。

## 10. Stage 2 验收案例

| 案例 | 验收条件 |
| --- | --- |
| 完整 Stage 1 请求 | 意图/实体/Skills/主辅仍有效；旧 15 项测试不能退步 |
| 只有 payment-service + 10:05 + 5xx | 工具补出 DBConnectionError/发布记录；Application 主、Database 辅；不能依赖用户写出 DB 错误码 |
| 10:05 故障、10:00 发布 | 发布前向回看命中；未来发布不参与因果线索 |
| 不同服务/环境、边界外记录 | 不混入本次 Evidence；范围校验和时间边界测试通过 |
| runbook_query / 问候 | 三个现场工具调用次数为零；Runbook 查询走新知识集合 |
| 缺服务或非 demo 缺日期 | 清晰澄清，不全库扫描，不悄悄补当前日期 |
| 范围内无数据 | 明确证据不足，不编造现场事实或唯一根因 |
| 一个工具失败/降级 | 保留另外两路证据，显示缺失来源，失败内容不当作事实 |
| 同一日志重复出现 | 稳定 ID 去重，domain_scores 不被条数无限抬高 |
| RAG 无结果/重排失败 | 状态真实，原问题和现场证据仍保留，不能伪报重排成功 |
| expected 隔离 | runtime loader 拒绝越界目录；运行镜像不含 evaluation 数据；改变 expected 不改变工具响应 |
| 第二组不同故障/较早历史案例 | 不固定输出连接池答案，不读取当前事件的标准答案 |
| 真实 HTTP /chat | 返回证据 ID、工具状态、时间假设、主辅与诊断语气；引用 ID 都存在，LLM 输出未截断 |

通过标准：工具筛选正确、现场事实可追溯、证据能实际影响辅助路由、旧行为无回归、真实请求完整执行。单条回复看起来合理不代表根因准确率已被证明。

## 评审后首先做什么

先实现第 1 批：QueryContext + Evidence + 一组明确标注的模拟数据 + 三个工具测试。先验证“在正确服务/环境/时间窗口里拿到正确记录”，再接 Agent。不要把三个工具、RAG、Memory、Router、API 一次全部改完才测试。
