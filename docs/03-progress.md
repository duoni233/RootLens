# RootLens 进度记录

更新日期：2026-10-04

## 一句话

EchoMind 原版是客服多 Agent 运行时。RootLens 复用运行时骨架，目标是内部系统故障诊断。2026-09-28 核心链路（真实 LLM 意图、实体、主辅路由、Skills、Agent 完整回复）验收通过，本地 15 个测试通过。RAG 查询改写/重排和画像更新仍有解析问题，不能视为完整系统全部通过。验收证据见 `05-first-stage-acceptance.md`。

2026-09-29：Stage 2 第 1 批证据层完成。新增 QueryContext、Operational Evidence/Bundle、模拟 INC-001 与三个查询工具；沿用原 ToolManager。隔离容器测试 52 项通过（Stage 1 15 + Stage 2 37），独立工具演示通过，未接入 Agent 或 /chat。详见 `07-stage2-batch1-acceptance.md`。

2026-09-29：第 2 批知识与 Memory 隔离完成。独立 rootlens_runbooks_v1、三份 Runbook 和一份较早模拟历史案例；RAG 状态、来源 ID/去重、证据增强 query 的独立契约；RootLens 默认禁止画像读写及跨会话召回，摘要失败/并发更新时不裁剪。94 项测试通过（15 + 37 + 42），包括固定向量的真实 Chroma 和临时真实 Redis；尚未用真实 LLM 重验 RAG，也未部署本批代码。详见 `08-stage2-batch2-acceptance.md`。

2026-09-30：第 3 批共用 DiagnosisPipeline 接通取证、增强检索、一次主辅路由与 /chat；114 项测试通过（原 94 + 新 20），包含真实 Chroma 测试集合和临时 Redis。当前运行容器仍是旧版本，未做真实 LLM 验收。详见 `09-stage2-batch3-acceptance.md`。

2026-09-30：第 4 批重建 RootLens Docker 并完成真实 LLM `/chat` 联调。短请求通过三路工具取得 9 条证据，RootLens RAG 改写/召回/重排均实际执行，Application 主、Database 辅；补齐证据驱动的 Database Skill 注入。缺条件澄清与 Runbook 不取证均通过。全量回归 115 项通过；原 EchoMind 容器未动。注意 `/eval/run` 尚未接入新管线，模拟数据不代表生产根因准确率。详见 `10-stage2-batch4-live-integration.md`。

2026-10-01：**Stage 3 已完成并关闭。** `/eval/run` 现与 `/chat` 共用 Intent Recognition + DiagnosisPipeline；六案例真实评测经人工审阅后，显式批准 `stage3-v2` / Judge schema `2` 为首份 RootLens baseline。Approved ID 为 `9bd1b2a57d5b411f87541bdcba521af4`，history 快照保留；批准后复评 `compatible=true`、`regression.status=compared`，确定性比较项 delta 均为 0，Judge 比较项均为 stable。详见 `15-stage3-closure.md`。这是一套 **six-case synthetic regression suite**，不代表生产准确率；仍有已知 RAG extra-hit noise，Judge v2 尚未经大规模人工校准。

2026-10-02：Stage 4-3 结构化诊断 API 与显式结构化评测已完成真实六案例验收：6/6 构建成功，`/chat.response` Markdown 保持兼容；Stage 3 approved baseline 仍 `compatible=true`，旧比较项 stable。全量离线测试 242 项通过。结构化契约验证不等于语义正确或生产准确率；Stage 4 后经人工确认关闭。详见 `18-stage4-3-structured-acceptance.md`。

2026-10-04：Stage 4 已经人工关闭，Stage 5-1 Trace 与 Stage 5-2 受控故障测试完成。Stage 5-3 的真实 Docker/模型验收确认 Trace 正常、273 项离线测试全过（含此前跳过的 3 项隔离 Redis 测试）、Stage 3 baseline 兼容；但 runbook 案例的真实结构化生成两次被正确拒绝，六案例结构化回归为 5/6。**Stage 5 暂不关闭**，先按 `21-stage5-3-reliability-trace-acceptance.md` 处理该质量问题，不进入 Stage 6。

2026-10-04：Stage 5-3.1B 为 Runbook 增加严格的内部生成格式，保留公开 `IncidentDiagnosis v1` 和 Validator；真实 Runbook 连续 3/3 成功，六案例结构化 6/6，Stage 3 baseline 兼容且 Judge stable，全量测试 282 项通过。额外一次 INC-004 人工抽查仍发现把日志空状态借 M401 指标 ID 写成 confirmed finding 的来源归因问题，因此 **Stage 5 仍待人工裁决，不自动封板或进入 Stage 6**。详见 `22-stage5-3-1b-runbook-structured-fix.md`。

2026-10-04：Stage 5-3.2B 保留原 `rootlens-demo:v1`，新增 v2 快照，仅从 INC-004 M401 指标摘要移除跨来源的日志状态；评测集另存 `stage3-v3`，原语义标签不变。全量离线测试 **286 passed、0 skipped**，新容器健康。首次真实 INC-004 调用中证据/工具状态正确，但模型供应商返回 HTTP 402 `Insufficient Balance`，结构化诊断 `assembler_failed`；按验收规则停止后续两次与六案例真实评测。旧 baseline 与新 suite 正确报告不兼容，未 promote。**Stage 5 仍未关闭**。详见 `23-stage5-3-2b-partial-evidence-fix.md`。

2026-10-04：供应商余额恢复后重启应用，INC-004 三次独立真实 `/chat` **3/3** 结构化成功，M401 仅支持 12% 的 5xx 事实，日志/发布空结果仍是工具状态。新 v2/v3 六案例真实评测 **6/6** 结构化成功、Judge **6/6** 有效；Stage 5 Trace/故障注入离线复测 **32/32** 通过，应用健康。完整原始评测在 `24-stage5-3-2b-evaluation-raw.json`，人工审查与已知限制在 `25-stage5-3-2b-live-acceptance.md`。旧 baseline 正确报告版本不兼容、未修改或 promote。**Stage 5 技术验收已达到供 Owner 决定封板的状态，但尚未正式关闭，也未进入 Stage 6。**

2026-10-04：**Stage 5 经 Owner 人工批准后正式关闭（COMPLETED）。** 使用已保存的 v3/v2 六案例原始报告显式 promote；新 approved baseline ID 为 `f79e1d913c7146088805290f7e1580e3`，旧 v2/v1 baseline `9bd1b2a57d5b411f87541bdcba521af4` 的历史快照保持原样。新 pointer 与历史快照哈希一致；用同一保存报告进行不调用模型的比较，`compatible=true`、`regression.status=compared`，可比较项 delta 均为 0。交付范围包含 DiagnosisTrace v1、受控故障注入、Runbook 结构化诊断稳定性修复、partial-evidence 来源归因修复、`rootlens-demo:v2`、`stage3-v3` 及新 baseline。完整离线回归 286/286，Stage 5 Trace/可靠性回归 32/32；已保存真实评测结构化 6/6、Judge v2 有效 6/6。详见 `26-stage5-final-closure.md`。这些仍只是六条模拟案例，不代表生产准确率；Stage 6 未开始。

2026-10-04：**Stage 6A Persistence Foundation 完成，Stage 6B 尚未开始。** 增加独立 `DiagnosisRun v1` 契约、SQLite/SQLAlchemy 单表 Repository 与结果投影，保存 Markdown、结构化诊断和 Trace 快照；不在共享的 `run_diagnosis` 内写历史，评测运行不能进入普通历史。17 项新增测试通过，含隔离 Redis 的全量离线回归 **303 passed、0 skipped**。未接 `/chat`、未新增 History API、未部署新版应用或前端；已批准的 Stage 5 baseline 未变。详见 `27-stage6a-persistence-foundation.md`。

2026-10-04：**Stage 6B 技术验收完成，待 Owner 人工确认正式关闭 Stage 6。** 普通 `/chat` 完成后保存 `DiagnosisRun`，返回真实的 `run_id/persistence_status`；历史列表、详情和独立 Trace API 均有默认关闭的开关及令牌保护。SQLite 独立 Docker 卷在应用重启与重建后保留记录，真实模型 smoke 保存和读回成功；数据库失败不拖垮诊断。新增 13 项测试，Stage 1-6 全量离线回归 **316 passed、0 skipped**，已批准的 Stage 5 baseline 哈希未变。详见 `28-stage6b-runtime-history-acceptance.md`。尚无前端、用户级权限或生产负载验收。

## 已完成

| 模块 | 原版 EchoMind | RootLens 当前实现 | 验证 |
| --- | --- | --- | --- |
| Intent | 客服细粒度意图 | 新增 service_incident、database_issue、deployment_issue 等故障意图；仍是单主意图 | 本地固定案例 |
| Entity | 订单号、金额、错误码等 | 增加 service_name、start_time、version、status_code，扩展 error_code | MVP 案例 |
| Router | General / Technical / Billing | GeneralOps / Application / Database / Infrastructure；意图、关键词、实体共同打分 | 主辅路由案例 |
| Skills | 客服、技术支持、账单规则 | 四份运维规则；按新 Agent 名称匹配并注入 system prompt | 本地测试 |
| 澄清 | 追问订单、退款等信息 | 追问服务、时间、错误码/日志/指标 | 本地测试 |
| P1 | CRITICAL 直接走升级分支 | 专业 Agent 保留诊断，结果标记 escalated | 本地测试 |

入口仍是 `api/main.py` 的 `/chat`，由共用 DiagnosisPipeline 串起 RootLens 取证、RAG 与路由。Memory 沿用第 2 批隔离配置；RootLens 默认 `/eval/run` 已复用相同核心诊断链并与 approved baseline 比较。Monitor 尚未作为 Stage 3 的改造目标。

## 本次固定验收

`app/test_rootlens_first_slice.py` 覆盖 MVP、单领域路由、信息不足、P1、Skill 匹配和可控模型下的最终意图。运行：

```powershell
cd E:\code\RootLens\app
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q -p no:cacheprovider test_rootlens_first_slice.py
```

本地测试使用可控模型替身，不验证真实模型回复质量。

## 未完成

1. 生产数据源接入、大规模回归评测和根因准确率仍未验证；当前六案例均为一致性模拟数据。
2. RAG 仍有与当前故障不直接相关的额外 Runbook 命中；Judge v2 未经大规模人工校准。当前意图兼容接口配置仍禁用 Embedding，实际启用 LLM 与 Pattern 两路。
3. 结构化 IncidentDiagnosis、执行 Trace、测试专用故障注入与 Stage 6 历史保存/查询均已实施；历史 Evidence/Knowledge 仅保存来源引用，源数据变化后不能完整还原原始正文。INC-004 的 v2 数据来源边界已通过真实稳定性验收；新 v2/v3 评测结果已获批为 baseline。
4. 清理残留的 EchoMind 客服意图、提示、数据和文档；决定原用户画像是否适合故障诊断场景。

Stage 5 已正式封板，Stage 6B 技术验收完成，等待 Owner 审阅后决定是否正式关闭 Stage 6。此时已有受控 History API，但还没有历史前端；六案例模拟数据、RAG extra-hit、Judge 校准不足及未做生产故障/负载研究等限制仍需保留。不要自动进入 Stage 7。
