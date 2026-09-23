# EchoMind 源码校验版模块图

> 作用：这不是重新发明作者架构图，而是把作者文档和我们读过的源码对齐，作为后续改造 RootLens 的参照基线。

## 1. 原始入口层

```text
Nginx
  -> FastAPI api/main.py
     -> /health
     -> /chat
     -> /search
     -> /knowledge/*
     -> /skills /skills/reload
     -> /monitor
     -> /metrics
     -> /eval/run
```

源码确认：`api/main.py` 中真实存在这些接口，其中 `/chat` 是主链路，`/eval/run` 是评测入口。

## 2. /chat 主链路

```text
ChatRequest
  -> MemoryManager.get_context()
  -> AgentOrchestrator.recognize_intent()
  -> _should_use_knowledge()
  -> MCPToolManager.search_with_rewrite()
  -> AgentOrchestrator.run()
  -> Agent.handle()
  -> MemoryManager.add_message()
  -> MemoryManager.update_profile() async task
```

源码确认：

- `MemoryManager` 读取 Redis 工作记忆、ChromaDB episodic、ChromaDB user_profile。
- `IntentRecognizer` 输出 intent、intent_group、confidence、source_scores、urgency、entities。
- RAG 不是所有问题都触发，而是由意图和关键词门控。
- `AgentOrchestrator` 会生成 primary/supporting 的结构化路由含义。
- 回复后写 Redis，并异步更新用户画像。

## 3. 多 Agent 编排层

```text
AgentOrchestrator
  -> IntentRecognizer
  -> RoutingDecision
     -> primary_agent
     -> supporting_agents
     -> routing_reason
     -> routing_confidence
  -> BaseAgent.handle()
     -> GeneralAgent
     -> TechnicalAgent
     -> BillingAgent
```

源码确认：

- 当前 Agent 类型是 `general / technical / billing`。
- 复合问题会根据领域分数得到主 Agent 和辅助 Agent。
- 专属 Agent 失败时可降级到 GeneralAgent。
- Monitor 写回的 penalty 会影响 routing_score。

## 4. RAG 与工具可靠性层

```text
MCPToolManager
  -> Tool(name="knowledge_search", handler=KnowledgeBase.search_handler)
  -> rewrite_query()
  -> call()
     -> cache
     -> circuit breaker
     -> schema validation
     -> timeout
     -> fallback
  -> multi-query recall
  -> dedupe
  -> LLM rerank
```

源码确认：

- `Tool` 中有 `cache_ttl / timeout_s / supports_rerank / fallback / stats / breaker`。
- `/search` 和 `/chat` 都可以走查询改写、多路召回、去重、重排。
- 知识库底层是 ChromaDB `knowledge_base` collection。

## 5. 记忆层

```text
MemoryManager
  -> Redis: working memory, summary
  -> ChromaDB episodic: historical conversation summaries
  -> ChromaDB user_profile: extracted user preference/entities
```

源码确认：

- Redis 使用 async client。
- ChromaDB 同步操作通过 `asyncio.to_thread()` 包起来。
- 会话消息达到压缩阈值后，旧消息摘要写入 Redis 和 episodic。

## 6. Skills 层

```text
SkillManager
  -> load skills/*
  -> match by agent type + keywords
  -> inject into Agent system prompt
```

源码确认：

- 支持 Markdown / JSON / TXT 技能文件。
- `/skills` 查看摘要，`/skills/reload` 热加载。

## 7. Monitor 与 Evaluation 闭环

```text
PerformanceMonitor
  -> collect orchestrator stats
  -> collect tool stats
  -> alerts / suggestions
  -> update routing penalties

EndToEndEvaluator
  -> IntentEvaluator Accuracy / Macro-F1
  -> real AgentOrchestrator.run()
  -> LLMJudge relevance / accuracy / completeness / helpfulness
  -> baseline regression
```

源码确认：

- Monitor 不只是展示，会写回路由降权。
- `/eval/run` 真实调用 Orchestrator，不是纯 mock。
- 当前 LLM Judge 依赖模型返回 JSON，存在解析失败时回退默认 0.5 分的情况。

## 8. 对原项目的判断

EchoMind 是一个教学/作品集取向的多 Agent 运行时骨架。它比普通聊天 Demo 完整：有 RAG、记忆、路由、工具治理、Monitor、Evaluation、Docker。但业务数据、工具真实性、Trace 持久化、失败注入和评测规模还不足以直接称为生产级系统。
