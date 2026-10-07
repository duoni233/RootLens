# RootLens 中文项目讲解与八股索引

这份材料用于**理解后再口述**，不是逐字背诵稿。依据当前代码、`03-progress.md` 和各阶段验收记录整理；早期的 `02-migration-mapping.md` 是目标蓝图，不能直接当成最终实现。最后核对日期：2026-10-07。

## 先把项目说成人话

RootLens 要解决的问题是：用户说“某个服务 5xx 激增”，系统不能只凭语言模型猜原因。它先弄清服务和故障时间，再查有时间、服务、环境边界的日志/指标/发布记录；用这些现场证据检索处理手册并决定由哪些 Agent 参与；最后把**已观察到的事实、尚待验证的原因、建议动作**分开输出。系统还能回看每一步、复现故障路径、保存一次诊断供历史查看。

**90 秒口述参考：**

> 我做的 RootLens 是在 EchoMind 已有的 Agent 编排和工具管理基础上，改造成一个面向内部服务故障的诊断演示系统。它的核心不是让多个 Agent 自由聊天，而是把一次请求串成“意图和实体识别、现场取证、Runbook 检索、一次主辅路由、结构化诊断”。比如 payment-service 发布后出现 5xx，系统会按服务、环境和时间查模拟日志、指标和发布记录，再把连接池耗尽作为有证据支持的现象，把“发布引起连接泄漏”保留为待验证假设。后来我把评测入口接到和 `/chat` 相同的主链，补了执行 Trace、可控故障测试、SQLite 历史和 React 工作台。当前只在六个合成案例上做了真实模型和回归验收，没接生产日志平台，也不宣称生产准确率。原项目运行时是复用并改造的部分，RootLens 的故障证据与诊断链是重点新增部分。

这段口述的关键是 **问题、链路、一个具体例子、验证方式、边界和来源**，不用一口气报完所有框架名。

## 一张链路图

```text
React -> POST /chat -> 当前会话 Redis Memory -> Intent / RootLens Entity
                        -> 是否需要现场取证？
                        -> QueryContext(服务、环境、事件时间、查询窗口)
                        -> ToolManager 并行查 logs / metrics / deployments
                        -> EvidenceBundle(证据 ID + ok/empty/failed/degraded)
                        -> 来源可追溯的词增强 query -> ChromaDB Runbook RAG
                        -> Evidence routing signal + 原有 domain score
                        -> 一次主辅 Agent 路由 -> Markdown 回复
                        -> IncidentDiagnosis 校验 + DiagnosisTrace
                        -> /chat 边界写入 SQLite DiagnosisRun
                        -> 控制台展示 / 历史详情 / Trace

/eval/run -> 同一核心诊断链 -> 与隔离的 expected 数据比较 -> 可选 Judge/基线比较
```

这里的 Trace 从 `run_diagnosis` 创建，不覆盖 `/chat` 前后的 Redis 读写，**不能称为完整 HTTP 分布式追踪**。`mcp/tool_manager.py` 中的 “MCP” 是原项目模块/类命名；目前没有证据说明 RootLens 对外实现了标准 MCP Server，不要这样介绍。

## 七个阶段分别做了什么

| 阶段 | 解决的问题、主要技术 | 能指给面试官看的位置 | 要会讲的基础知识 |
| --- | --- | --- | --- |
| Stage 1 识别与分工 | 将客服意图/Agent 改为故障意图、Application/Database/Infrastructure 等；仍是**单主意图**，用领域分数选主辅 Agent，Skill 注入规则 | `app/core/intent_recognizer.py`、`app/agents/agent_orchestrator.py`、`app/skills/` | Python 类与对象、Enum/Pydantic、异步调用、路由分数、主辅与兜底 |
| Stage 2 现场事实与知识 | Pydantic QueryContext/Evidence；三个模拟工具沿用旧 ToolManager 的超时/缓存/熔断；独立 Chroma 集合、RAG 改写/召回/重排；Redis 会话保留、旧客服画像与跨会话召回默认关闭；`DiagnosisPipeline` 串起并只做一次最终路由 | `app/core/evidence.py`、`app/mcp/incident_tools.py`、`app/mcp/knowledge_base.py`、`app/core/diagnosis_pipeline.py` | 时间窗与时区、并发取证、去重、向量检索、缓存/降级、数据来源隔离 |
| Stage 3 评测对齐 | `/eval/run` 复用 `/chat` 核心链；expected 与 runtime 数据隔离；确定性指标、可选 LLM Judge、版本化 approved baseline | `app/evaluation/rootlens_evaluator.py`、`rootlens_cases.py`、`rootlens_metrics.py`、`rootlens_judge.py` | 指标分子/分母、Macro-F1、评测泄漏、Judge 失效处理、回归与指纹 |
| Stage 4 结构化结论 | 保留旧 Markdown 响应，额外构建 `IncidentDiagnosis v1`；校验 Evidence/Knowledge 引用和高风险动作审批标记；构建失败明确返回状态 | `app/core/incident_diagnosis.py`、`diagnosis_assembler.py`、`diagnosis_validation.py` | Schema 与校验、向后兼容、模型 JSON 不稳定、引用存在性不等于语义真实 |
| Stage 5 过程与故障路径 | 请求范围内的 `DiagnosisTrace`；测试专用受控故障注入；验证 Tool 空结果/失败、Agent fallback、Assembler 坏 JSON 等降级 | `app/core/diagnosis_trace.py`、`app/test_support/failure_controller.py`、`app/evaluation/rootlens_reliability.py` | UTC 与 monotonic、并发步骤、empty/failed/degraded/skipped、故障隔离 |
| Stage 6 历史 | `DiagnosisRun v1` 把输入、结论、Trace 归为同一次运行；SQLAlchemy + SQLite Repository；只有普通 `/chat` 在完成后保存，评测不写用户历史；令牌保护历史 API | `app/persistence/`、`app/api/main.py` | 持久化边界、事务/索引/分页、失败不拖垮主请求、最小权限 |
| Stage 7 界面 | React + TypeScript + Vite 工作台：新诊断、澄清补充、历史筛选、详情/Trace；区分“解读旧档案”和“重新取证” | `frontend/src/pages/`、`frontend/src/lib/api.ts`、`app/core/history_explanation.py` | 状态管理、请求契约、会话边界、token 的演示级保护 |

Stage 1–6 有相应验收记录；Stage 7 的历史解读已有一次真实模型 API 冒烟测试，但**浏览器双模式追问仍需 Owner 最终确认**。最新记录的 322 项后端、22 项前端测试是回归证据，不等于任意新故障都能诊断。

## 技术为什么这样选，而不是随便换一个

| 选择 | 这里解决什么 | 为什么第一版没选常见替代方案；代价是什么 |
| --- | --- | --- |
| FastAPI + Pydantic | 异步 I/O 接口、请求/响应契约、结构化字段校验、Swagger 调试 | Django 功能更全但本项目不是管理后台；Flask 更轻但需自己补更多契约。FastAPI 不会让 CPU 运算自动并行 |
| 沿用 EchoMind ToolManager | 已有参数校验、超时、缓存、熔断和 fallback，三工具只实现业务查询 | 未引入 LangGraph/CrewAI；换框架会扩大迁移与回归面。当前也不是标准 MCP Server |
| 版本化 JSON 模拟数据 | 日志、指标、发布能保持一致，来源 ID 稳定，可离线复现失败案例 | 不直接接 ELK/Prometheus/发布平台：缺真实授权和数据，先验证契约。代价是不能宣称实时取证或生产效果 |
| Redis + ChromaDB + SQLite 分工 | Redis 放短期会话，Chroma 放 Runbook 向量检索，SQLite 放可分页历史 | 不把三种需求塞进一个存储；但多组件增加部署复杂度。SQLite 适合本地单机演示，不代表生产并发方案 |
| 单主 Intent + Evidence 领域信号 | 保留原接口，允许日志/指标影响主辅路由；`max(原分数, 证据下限)` 防重复日志无限抬分 | 未改成多标签 Intent 或两次路由。分数是**启发式相关度，不是根因概率**；阈值未做大样本优化 |
| RAG 改写 + 并行召回 + 去重 + 重排 | 弥补单一提问角度，并让有来源的故障词影响检索 | 未换 Milvus 或复杂检索框架；目前有额外 Runbook 命中，也没有可证明的真实场景 Recall 提升数字 |
| 确定性指标 + LLM Judge | 前者检查意图/路由/证据等可结构化比较项，后者辅助看诊断文本质量 | 不只看 Judge 平均分；Judge 失败不填伪分，且 v2 尚未大规模人工校准。approved baseline 只能比较同版本 suite/dataset |
| 自定义 Trace + 测试专用注入 | 看清哪一步慢/失败，并可复现降级而不开放危险注入接口 | 没有上 OpenTelemetry/Grafana 或生产故障演练；Trace 只覆盖诊断范围，外部平台和高并发仍待做 |
| SQLite + SQLAlchemy Repository | 快速实现持久化、查询和快照版本检查；数据库失败不阻塞诊断回答 | 先不引入 PostgreSQL/Alembic；缺迁移、租户隔离和生产负载验证，后续若真多用户再升级 |
| React/TypeScript + 现有 Nginx | 结构化事实/假设、历史和 Trace 需要多视图交互；类型约束 API 使用 | 未用简单聊天页或 Streamlit；前端更费工程量。当前共享令牌、HTTP 只适合可信私有演示 |

**特别注意**：`requires_approval=true` 只是建议动作的风险标记，当前没有生产回滚执行器或完整的人审工作流。

## 面试时可以讲的四个真实问题

1. **评测链与实际链不一致。** 早期 `/eval/run` 绕过新的取证/RAG Pipeline，分数不能代表 `/chat`。修复是让 Evaluator 只投影运行输入并复用同一核心链，结束后才读 expected 计算指标。验证点是六案例与标签隔离测试。参见 `docs/11-stage3-batch2-acceptance.md`。
2. **结构化结果有 ID 不等于事实正确。** Stage 4 曾出现模型输出超长/坏 JSON，Assembler 调整内部生成约束并保留原 Markdown；另有 partial-evidence 案例把“日志为空”借指标 ID 写成确认事实。后者通过 v2 模拟源记录的来源归因修正和人工复验处理；Validator 仍只能保证引用合法，不能证明语义蕴含。参见 `docs/18-stage4-3-structured-acceptance.md`、`docs/23-stage5-3-2b-partial-evidence-fix.md`。
3. **故障不应把整条请求打崩。** 在测试层注入日志超时、RAG 失败、辅 Agent 失败或 Assembler 坏 JSON。Trace 分开记录出错组件；可用的其他证据和 Markdown 尽量保留；empty 不算 failed。验证的是 12 个确定性合成场景，不是生产故障恢复率。参见 `docs/20-stage5-failure-injection-reliability.md`。
4. **历史追问被误当成新故障。** 旧 UI 把原问题、摘要和追问反复拼接后送 `/chat`，结果 QueryContext 先因时间歧义要求补充，根本没走到解释。改为“解读归档诊断”与“重新诊断”两个入口；前者不调用现场工具/RAG，后者是新运行。已做一次真实解读 API 检查，浏览器体验还需最终确认。参见 `docs/29-stage7-diagnosis-console-acceptance.md`。

讲问题时按 **现象 -> 定位 -> 改动 -> 如何验证 -> 仍有什么边界**，比一句“优化了系统稳定性”更可信。

## 高频追问与短答

先把此前看代码时容易卡住的语法对应上：`@app.post("/chat")` 是 FastAPI 注册路由的装饰器，`tags` 只影响 Swagger `/docs` 分组；`Optional[str] = None` 表示可为字符串或 `None` 且默认缺省；`self._client` 是实例持有的依赖对象；`**kwargs` 是把字典展开为关键字参数；`isinstance(x, list)` 检查运行时类型；`item.get("title", "未命名")` 是字段缺失时用默认值；`getattr(intent, "value", intent)` 是属性不存在时退回原对象。类型提示帮助 IDE/检查工具理解代码，普通 Python 参数不会仅因写了 `: str` 就自动校验；FastAPI/Pydantic 的请求模型另有运行时校验。

1. **为什么 `asyncio.gather`？** 三种取证互不依赖，I/O 等待可重叠；它不让纯 CPU 计算自动变快。每个工具仍需超时和单独状态，避免某个失败被误认为全空。
2. **empty、failed、degraded 有何区别？** empty 是查询成功但没有记录；failed 是本次调用失败；degraded 是降级/部分结果可用。不能把降级说明文本当作现场 Evidence。
3. **为什么发布时间接近故障不算根因？** 时间相关只产生调查线索；还要对照版本差异、连接生命周期、数据库和流量数据。Evidence 是已观察事实，Hypothesis 是待验证解释。
4. **为什么用稳定 Evidence ID？** 多查询去重、结构化引用、Trace 和评测都能指向同一源记录；`retrieved_at` 可以变化，源身份不能随请求变化。
5. **RAG 改写/重排失败怎么办？** 保留原查询或原顺序，并记录 failed/degraded；不能标成 performed，也不能让 fallback 文本假装命中文档。
6. **Redis、Chroma、SQLite 能互换吗？** 不能直接互换职责：当前会话、语义检索和可查询历史需要不同访问模式。生产系统可能重新选型，但应先量化负载和一致性要求。
7. **`IntentResult` 是多标签吗？** 当前是单个主意图；Evidence 的领域信号帮助选主辅 Agent，不能把它说成模型预测的多标签概率。
8. **结构化校验能防幻觉吗？** 只拦无效字段、未知引用和违反风险策略的动作；即使 ID 存在，文字也可能曲解证据，所以还有人工来源审查。
9. **为什么评测答案要物理/逻辑隔离？** Agent、RAG、工具只读 runtime；expected 只在结果产生后由 Evaluator 读取，否则就是答案泄漏，分数没有意义。
10. **为什么六案例 6/6 不能叫准确率 100%？** 样本少且合成、与实现共同演进，不代表真实故障分布；Judge 也未大规模人工校准。
11. **Trace 时间为什么既有 UTC 又有 monotonic？** UTC 用来对齐事件和展示开始/结束，monotonic 用来计算耗时，避免系统时钟调整影响时长；并行步骤不能按数组位置理解为先后执行。
12. **为什么 History token 不算用户鉴权？** 它是私有演示用共享秘密，没有用户身份、角色、租户或 TLS；不能把当前页面开放到公网并称为企业级权限体系。

## 练习顺序与诚实边界

第一遍只用上面的 90 秒口述和链路图，说清“请求怎么走”。第二遍每次选一个阶段，拿一个具体案例指到代码和验收记录。第三遍随机抽本页的追问，用自己的话回答，不需要记住每个函数参数。

不要说“从零实现 EchoMind 的 Agent Runtime”“接入了真实生产日志”“根因准确率 100%”“实现了完整 MCP/人审回滚/生产级认证”。更准确的说法是：**基于已有运行时做了场景改造与工程验证；需求拆分、方案审查和验收由自己负责，AI 工具辅助实现；能指出每一项能力的真实边界。**
