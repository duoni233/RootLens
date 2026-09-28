# 第一阶段核心链路验收

日期：2026-09-28。范围：真实 LLM 意图、实体、主辅路由、Skill 注入、Agent 完整回复。

## 最小修正

- `core/llm_utils.py`：增加 DeepSeek 非思考参数辅助函数，仅 api.deepseek.com 主机匹配时返回 extra_body；其他厂商不受影响。
- `core/intent_recognizer.py`：该次意图调用使用非思考参数，保留 256-token 预算，并记录结束原因。
- `agents/agent_orchestrator.py`：Agent 回复使用非思考参数，输出预算从 1024 提高为 4096，记录结束原因。
- `test_rootlens_first_slice.py`：增加参数匹配和调用参数回归测试，15 个全部通过。

不改模型名称、API Key、Prompt、Router、RAG 或 Memory 逻辑。原 EchoMind 不受影响。

官方兼容说明：https://api-docs.deepseek.com/guides/anthropic_api/ （thinking 参数支持，旧 SDK 通过 extra_body 传入）。

## 真实验收结果

使用全新会话 rootlens-acceptance-20260928，提交原约定 MVP 请求。

| 项目 | 证据 |
| --- | --- |
| /chat | HTTP 200 |
| 最终 Intent | deployment_issue，intent_group=application |
| LLM 输出 | end_turn，59 个输出 token，JSON 解析成功 |
| 各路评分 | llm=0.9，pattern=0.75，embedding=0.0 |
| 融合置信度 | 0.765；LLM 的加权得分获胜，不是关键词兜底 |
| Embedding | 第三方 base_url 配置下禁用，未宣称三路同时运行 |
| 实体 | service_name=payment-service，start_time=10:05，version=v2.3.7，status_code=5xx，error_code=DBConnectionError |
| 主辅 | application 主，database 辅 |
| Skills | 日志确认应用服务故障诊断、数据库故障诊断分别注入 |
| Application 回复 | end_turn，1214 个输出 token |
| Database 回复 | end_turn，924 个输出 token |
| 回复风格 | 诊断语气，区分事实和待验证假设，没有因 token 预算截断 |
| 部署 | 五个 RootLens 容器 healthy；后端、Nginx 与原 EchoMind 健康接口均 ok |

本次 LLM 把包含“刚发布”的请求判断为 deployment_issue，而不是局部关键词测试中的 service_incident。两者都属于应用域，主辅路由符合约定。若以后要求精确标签，应在评测集定义统一标注标准，而不是为了单条样例强行覆盖模型结果。

## 不能据此宣称的能力

- 单条真实请求通过不是整体诊断准确率或生产可用性的证明。
- RAG 改写和重排仍记录 JSON 解析失败，检索也仍含旧客服文档。
- 异步画像更新仍记录 JSON 解析失败。
- 本轮未改上述调用，未验收新故障工具、结构化诊断、Trace 或前端。

下一步应先列清 RAG 与画像的保留/改造范围，并在故障知识库阶段解决相应兼容问题；无需重新推翻已通过的核心链路。
