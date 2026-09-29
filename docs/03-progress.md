# RootLens 进度记录

更新日期：2026-09-29

## 一句话

EchoMind 原版是客服多 Agent 运行时。RootLens 复用运行时骨架，目标是内部系统故障诊断。2026-09-28 核心链路（真实 LLM 意图、实体、主辅路由、Skills、Agent 完整回复）验收通过，本地 15 个测试通过。RAG 查询改写/重排和画像更新仍有解析问题，不能视为完整系统全部通过。验收证据见 `05-first-stage-acceptance.md`。

2026-09-29：Stage 2 第 1 批证据层完成。新增 QueryContext、Operational Evidence/Bundle、模拟 INC-001 与三个查询工具；沿用原 ToolManager。隔离容器测试 52 项通过（Stage 1 15 + Stage 2 37），独立工具演示通过，未接入 Agent 或 /chat。详见 `07-stage2-batch1-acceptance.md`。

## 已完成

| 模块 | 原版 EchoMind | RootLens 当前实现 | 验证 |
| --- | --- | --- | --- |
| Intent | 客服细粒度意图 | 新增 service_incident、database_issue、deployment_issue 等故障意图；仍是单主意图 | 本地固定案例 |
| Entity | 订单号、金额、错误码等 | 增加 service_name、start_time、version、status_code，扩展 error_code | MVP 案例 |
| Router | General / Technical / Billing | GeneralOps / Application / Database / Infrastructure；意图、关键词、实体共同打分 | 主辅路由案例 |
| Skills | 客服、技术支持、账单规则 | 四份运维规则；按新 Agent 名称匹配并注入 system prompt | 本地测试 |
| 澄清 | 追问订单、退款等信息 | 追问服务、时间、错误码/日志/指标 | 本地测试 |
| P1 | CRITICAL 直接走升级分支 | 专业 Agent 保留诊断，结果标记 escalated | 本地测试 |

入口仍是原 `api/main.py` 的 `/chat`。RAG、Memory、Monitor、Evaluation、Docker 配置目前仍主要是 EchoMind 原实现，不能当作已完成的 RootLens 业务能力。

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

1. RAG 改写/重排和画像更新仍有模型输出解析问题，尚未使用本次两处调用的兼容处理。当前兼容接口配置禁用了 Embedding，实际启用 LLM 与 Pattern 两路。
2. 与故障场景相符的 Runbook / 历史 Incident 知识库；已实现的模拟 logs、metrics、deployments 工具尚未接入 /chat。
3. 结构化 IncidentDiagnosis、执行 Trace、统一评测集和故障注入。
4. 清理残留的 EchoMind 客服意图、提示、数据和文档；决定原用户画像是否适合故障诊断场景。

下一步：Stage 2 第 2 批，RootLens 专用知识集合、Runbook、必要 RAG 兼容与 Memory 隔离。之后第 3 批再让证据影响路由并接入真实 /chat。当前没有完成整个 Stage 2。
