# RootLens 进度记录

更新日期：2026-09-24

## 一句话

EchoMind 原版是客服多 Agent 运行时。RootLens 复用运行时骨架，目标是内部系统故障诊断。目前完成了第一条请求的意图、实体、路由、Skills 和紧急度的本地逻辑验证；完整 HTTP /chat 尚未联调。

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

1. RootLens `.env` 和 Docker 联调：先验证实际三路识别，再验证完整 `/chat` 返回与服务启动。
2. 与故障场景相符的 Runbook / 历史 Incident 知识库，以及 logs、metrics、deployments 工具。
3. 结构化 IncidentDiagnosis、执行 Trace、统一评测集和故障注入。
4. 清理残留的 EchoMind 客服意图、提示、数据和文档；决定原用户画像是否适合故障诊断场景。

下一关的成功标准：MVP 请求通过真实 `POST /chat`，返回预期实体与 Application 主、Database 辅的路由，两个 Agent 确实拿到对应 Skills。随后再评估诊断回复质量。
