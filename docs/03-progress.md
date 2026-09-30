# RootLens 进度记录

更新日期：2026-09-30

## 一句话

EchoMind 原版是客服多 Agent 运行时。RootLens 复用运行时骨架，目标是内部系统故障诊断。2026-09-28 核心链路（真实 LLM 意图、实体、主辅路由、Skills、Agent 完整回复）验收通过，本地 15 个测试通过。RAG 查询改写/重排和画像更新仍有解析问题，不能视为完整系统全部通过。验收证据见 `05-first-stage-acceptance.md`。

2026-09-29：Stage 2 第 1 批证据层完成。新增 QueryContext、Operational Evidence/Bundle、模拟 INC-001 与三个查询工具；沿用原 ToolManager。隔离容器测试 52 项通过（Stage 1 15 + Stage 2 37），独立工具演示通过，未接入 Agent 或 /chat。详见 `07-stage2-batch1-acceptance.md`。

2026-09-29：第 2 批知识与 Memory 隔离完成。独立 rootlens_runbooks_v1、三份 Runbook 和一份较早模拟历史案例；RAG 状态、来源 ID/去重、证据增强 query 的独立契约；RootLens 默认禁止画像读写及跨会话召回，摘要失败/并发更新时不裁剪。94 项测试通过（15 + 37 + 42），包括固定向量的真实 Chroma 和临时真实 Redis；尚未用真实 LLM 重验 RAG，也未部署本批代码。详见 `08-stage2-batch2-acceptance.md`。

2026-09-30：第 3 批共用 DiagnosisPipeline 接通取证、增强检索、一次主辅路由与 /chat；114 项测试通过（原 94 + 新 20），包含真实 Chroma 测试集合和临时 Redis。当前运行容器仍是旧版本，未做真实 LLM 验收。详见 `09-stage2-batch3-acceptance.md`。

## 已完成

| 模块 | 原版 EchoMind | RootLens 当前实现 | 验证 |
| --- | --- | --- | --- |
| Intent | 客服细粒度意图 | 新增 service_incident、database_issue、deployment_issue 等故障意图；仍是单主意图 | 本地固定案例 |
| Entity | 订单号、金额、错误码等 | 增加 service_name、start_time、version、status_code，扩展 error_code | MVP 案例 |
| Router | General / Technical / Billing | GeneralOps / Application / Database / Infrastructure；意图、关键词、实体共同打分 | 主辅路由案例 |
| Skills | 客服、技术支持、账单规则 | 四份运维规则；按新 Agent 名称匹配并注入 system prompt | 本地测试 |
| 澄清 | 追问订单、退款等信息 | 追问服务、时间、错误码/日志/指标 | 本地测试 |
| P1 | CRITICAL 直接走升级分支 | 专业 Agent 保留诊断，结果标记 escalated | 本地测试 |

入口仍是 `api/main.py` 的 `/chat`，但现在由共用 DiagnosisPipeline 串起 RootLens 取证、RAG 与路由。Memory 沿用第 2 批隔离配置；Monitor 和 Evaluation 仍主要是 EchoMind 原实现，尤其 `/eval/run` 尚未覆盖新管线。

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

1. 真实 LLM 下的 RAG 改写/重排需再次联调；确定性兼容测试已通过，但不能替代真实模型验收。当前意图兼容接口配置仍禁用 Embedding，实际启用 LLM 与 Pattern 两路。
2. 新管线已在源码和确定性 HTTP 测试接入 /chat，但部署生效与真实模型表现待验收；现有运行容器仍使用旧镜像。
3. 结构化 IncidentDiagnosis、执行 Trace、统一评测集和故障注入。
4. 清理残留的 EchoMind 客服意图、提示、数据和文档；决定原用户画像是否适合故障诊断场景。

下一步：第 4 批 Docker 构建与真实完整 /chat 验收。当前没有完成整个 Stage 2。
