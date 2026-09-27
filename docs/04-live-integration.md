# 第一阶段真实联调

日期：2026-09-27。结论：部署与请求链路可运行，LLM 意图输出验收未通过。

## 配置变化

- `app/.env` 沿用原 EchoMind 的模型配置；被 Git 和 Docker 构建上下文忽略。
- Compose 项目为 rootlens，容器名为 rootlens-*，数据卷独立。
- 后端 8100、ChromaDB 8101、Redis 6380、Prometheus 9190、Nginx 8081。
- 独立网段 172.29.0.0/16，Nginx 的 metrics 允许网段同步调整。
- 容器内 CHROMA_HOST=chromadb、CHROMA_PORT=8000。
- Compose 内部应用服务名仍为 echomind，以沿用现有 Nginx 和 Prometheus 的内部目标；不会连接到原项目网络。

## 实测

请求：payment-service 从 10:05 开始 5xx 激增，刚发布 v2.3.7，日志里有 DBConnectionError，帮我判断原因。

| 项目 | 结果 |
| --- | --- |
| Compose config / up --build | 成功 |
| 五个容器 | healthy |
| 后端与 Nginx /health | ok |
| POST /chat | HTTP 200 |
| Intent | service_incident，intent_group=application，confidence=0.75 |
| Entity | payment-service、10:05、v2.3.7、5xx、DBConnectionError |
| 主辅路由 | application 主，database 辅 |
| Skills | 日志确认应用、数据库两份规则实际注入 |
| 回复 | 故障诊断语气；区分已知事实和待验证原因，但有截断迹象 |
| Intent 分支 | LLM 调用失败后 Pattern 兜底；Embedding 因兼容接口配置禁用 |

## 当前阻塞

模型是沿用配置的 deepseek-v4-flash。真实意图调用 HTTP 成功，但 JSON 解析失败。追加诊断得到：

```json
{
  "max_tokens_requested": 256,
  "stop_reason": "max_tokens",
  "output_tokens": 256,
  "blocks": [{"type": "thinking", "thinking_chars": 953}],
  "extracted_text_chars": 0
}
```

因此并非 Key 或网络不可用，而是当前输出预算耗尽时尚无可解析文本。查询改写、重排和画像更新也记录了 JSON 解析失败；未独立检查这些调用的原始响应，不能断言原因完全相同。Agent 回复有截断迹象，也尚未独立捕获其结束原因。

此外，知识库仍自动导入原客服六篇文档，本次检索出现配送、会员等无关内容。按本轮范围未改 RAG。ChromaDB 遥测兼容错误不影响本次连接和查询。

## 下一步

先限定在模型输出预算/思考模式兼容问题上，修正后重测 LLM Intent 和回复完整性；通过后再进入故障知识库与查询工具阶段。本次未改业务 Python 模块。

Swagger：http://localhost:8100/docs；Nginx 入口：http://localhost:8081/docs。
