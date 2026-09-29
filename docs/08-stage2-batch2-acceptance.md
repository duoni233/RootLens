# Stage 2 第 2 批验收：知识层、RAG 兼容、Memory 隔离

日期：2026-09-29。代码与确定性验证通过；可以评审后进入第 3 批。尚未完成整个 Stage 2，未部署本批代码。

## 1. 文件与理由

| 文件 | 改动理由 |
| --- | --- |
| `app/mcp/knowledge_base.py` | 独立集合参数、禁止新集合加载客服种子、稳定 document/chunk ID、source_ref/metadata、upsert 与旧分片清理、空库与距离过滤 |
| `app/mcp/tool_manager.py` | 保留原公开调用；增加逐次 RAG 状态结果、DeepSeek 兼容参数、JSON/索引校验、按 chunk ID 去重、排除降级文本、缓存保留加工状态 |
| `app/core/rootlens_config.py` | RootLens 的集合名与隔离开关默认值；拒绝指向旧 knowledge_base，参数错误不悄悄放行 |
| `app/core/rag_query.py` | 独立的证据增强检索契约；不调用 Agent，不加载标准答案，不改原 message |
| `app/memory/conversation_memory.py` | 可配置禁用画像与跨会话召回；摘要空/截断/失败保护；Redis WATCH + MULTI 原子提交摘要与裁剪 |
| `app/api/main.py` | 启动时使用新知识集合、载入知识文件、显式传隔离参数；画像关闭时不创建后台任务；知识上下文排除 fallback、附来源；/search 返回真实阶段状态 |
| `app/.env.example` | 公开四个 RootLens 配置项；未改实际 .env 或 API Key |
| `app/knowledge/rootlens/manifest.json` | 明确来源文件、稳定文档 ID、知识类别、服务与发布时间 |
| `app/knowledge/rootlens/db-connection-pool.md` | 数据库连接池排查步骤与证据不足的边界，不固定当前根因 |
| `app/knowledge/rootlens/application-5xx.md` | 5xx 的应用/依赖区分，不把所有 5xx 判作连接池问题 |
| `app/knowledge/rootlens/deployment-troubleshooting.md` | 发布前向回看与配置对照；相关不等于因果，不执行回滚 |
| `app/knowledge/rootlens/incident-20260814.md` | 较早的 order-service 流量/CPU 模拟历史事件，不是当前 payment-service 的答案 |
| `app/test_rootlens_knowledge_memory.py` | 新增 42 项固定测试，其中 3 项使用真实临时 Redis |
| `docs/03-progress.md`、`06-stage2-design-v0.1.md`、本文 | 记录边界、验证类型与剩余任务 |

没有改 AgentOrchestrator、domain_scores、IntentRecognizer、第一批 Evidence/Tool 文件及其测试。没有新增 DiagnosisPipeline、IncidentDiagnosis、Trace、数据库、前端或新 Agent 框架。

## 2. 知识隔离

- API 启动默认使用 `rootlens_runbooks_v1`。`ROOTLENS_KNOWLEDGE_COLLECTION` 可显式指定另一个 rootlens_ 集合，不接受 knowledge_base。
- KnowledgeBase 的旧构造方式仍保留 knowledge_base 默认值，方便旧调用兼容；只有该旧集合且为空时才允许旧种子初始化。
- RootLens 显式传 load_default_docs=False，从 knowledge/rootlens 的 manifest 读取四份文件；不会扫描 datasets/evaluation 或加载客服默认文档。
- 每个分片 ID 如 `RL-RB-DB-001:c0000`，带 source_ref、document_id、content_hash、chunk_index、总分片数、知识类别、来源类型、服务、发布时间、模拟标记。
- 同一文档重复载入采用 upsert；内容变短时移除该文档多余的旧分片。不会删除其他文档或其他集合。
- 测试中在同一真实 Chroma 客户端保留原客服集合，初始化新集合两次，新集合仍只有四个分片、旧客服数据不变。
- 运行目录和镜像中的知识文件与 evaluation 文件继续分开。此前 .dockerignore 的答案排除规则保留；本批没有重新构建镜像验收这一规则。

RootLens 新集合使用 cosine 距离，默认 max_distance=0.8，是可配置的拒绝无关结果门槛，不是路由阈值、概率置信度或经过优化的召回指标。原集合距离配置不强行修改。

## 3. RAG 实际代码链

```text
检索 query
  -> rewrite_query_result：可控开关、非思考兼容参数、JSON 数组校验
  -> 保留原 query + 去重子查询
  -> 现有 call：缓存 / 熔断 / 校验 / 超时 / handler
  -> Chroma 查询：返回稳定 chunk_id、document_id、source_ref、metadata
  -> 合并：同一集合的 chunk_id 去重，不因 score 不同而重复
  -> 排除失败或 fallback 文本；部分召回失败明确记录
  -> rerank_result：支持且数量超 Top-K 时调用模型，校验索引是完整排列
  -> Top-K 与阶段状态
```

重排 Prompt 优先呈现标题和内容，避免新增 metadata 占掉原来 200 字序列化预算导致模型看不到正文。

ToolResult 保留旧字段，新增 rewrite_status、retrieval_status、rerank_status、stage_errors。没有使用共享 last_status，因此并发请求不相互覆盖状态。

| 状态 | 本批含义 |
| --- | --- |
| performed | 阶段实际执行且结果校验通过；正常检索无结果也可以 performed + 空列表 |
| skipped | 开关关闭、工具不支持重排、候选数不超过 Top-K 等，不伪报模型调用 |
| failed | 调用/解析/校验失败；rewrite 保留原 query，rerank 保留原顺序，状态仍为 failed |
| degraded | 工具返回降级说明，或部分子查询失败；仅保留真实召回结果，不把降级文本算作命中 |

`reranked=True` 仅对应有效重排成功。缓存返回 cached=True，保留缓存结果原来的加工状态与错误，不意味着本次又调用模型；工具总成功与某个 RAG 阶段成功也不混淆。

兼容 wrapper `rewrite_query` / `_rerank` 仍返回 list；`call` / `search_with_rewrite` 仍返回 ToolResult。缓存内部多保存状态，超时/熔断主体未重写。

## 4. Evidence-enhanced query：只做独立契约

```python
retrieval = build_retrieval_query(
    original_message,
    evidence=bundle,
    terms=[EvidenceTerm("DBConnectionError", evidence_id)],
)
result = await tool_manager.search_with_rewrite("knowledge_search", retrieval.query)
```

它只接受 Bundle 内有效日志证据的来源：工具状态为 ok，服务、环境、数据集版本和日志窗口匹配。term 必须出现在对应 error_code/message 中；无出处的猜测被忽略。

最多六个去重 term，每个最长 64 字符，附加部分最长 512 字符；保留原 message，另建 query，返回引用 ID。没有有效证据/term 时返回完全相同的原问题。默认可从日志字段提取受限词，不读 expected_diagnosis，也不使用模型生成根因。

查询示例：原问题 payment-service 10:05 开始 5xx 激增，另加现场来源支持的 DBConnectionError 和 connection pool exhausted。固定向量测试证明检索排名会随证据词变化，原 message 不变；不据此宣称真实模型召回率提升。

runbook_query 可以直接检索，不需要现场三个工具。本批没有把增强函数或三个工具接到 /chat；现有 /chat 仍使用原问题检索，但知识来源在下一次部署后会切换到新集合。

## 5. Memory 保留与默认关闭

| 能力 | 本批状态 |
| --- | --- |
| Redis 最近消息读写、当前会话摘要、24 小时 TTL | 保留 |
| 压缩成功后的 episodic 存档 | 保留；不自动召回其他会话 |
| user_profile 读取和更新 | RootLens 默认 false；关闭时不创建画像集合、不读取、不更新、不创建 API 后台画像任务 |
| 跨会话 episodic 自动注入 | RootLens 默认 false，包括 get_context 和内部读取方法的保护 |

MemoryManager 类的两个新参数默认仍为 True，以保留原调用方式；RootLens API 从显式配置 helper 传 false。两者不要混为一谈，直接复用该类做 RootLens 独立脚本时也应传 memory_options()。

配置项：ROOTLENS_USER_PROFILE_ENABLED、ROOTLENS_EPISODIC_RECALL_ENABLED；支持 true/false/1/0，非法值报错。没有重命名成 service_profile，也没有删除现有 profile/episodic 数据。

摘要保护：读取完整待压缩消息快照，失败、空文本、max_tokens 截断时直接返回，不用占位摘要替代旧消息。成功后 WATCH 检查会话未更新，MULTI 同时写摘要和 LTRIM 保留最新五条；并发变更则取消本次提交。修正了原来的删除/逐条重写顺序风险。

摘要与可选画像调用沿用 DeepSeek 非思考兼容 helper；只匹配 api.deepseek.com，其他厂商不发送该额外参数。Redis TTL 仍是保留策略，摘要失败不会阻止正常 TTL 到期。

## 6. 验证与结果

最终：94 passed in 13.64s，无跳过。

- Stage 1：15 项全部通过，原测试未改。
- Stage 2 第 1 批：37 项全部通过，原测试未改。
- 本批：42 项全部通过。

覆盖独立集合、无客服种子、重复初始化、稳定来源与旧分片清理、正确 Runbook/无关查询、rewrite/rerank 各种结果、完整索引校验、兼容参数、正文入重排 Prompt、并行去重、缓存状态、fallback 排除、部分失败、证据增强/答案不影响查询、越界路径拒绝、默认 Memory 隔离、Redis 会话读写与 TTL、摘要异常/空/截断/并发保护。

测试真实性明确区分：

- 使用真实 ChromaDB PersistentClient、真实向量索引和 upsert；Embedding 是可控固定向量，不是生产 MiniLM 模型。
- LLM 使用可控替身，断网运行；验证调用参数和解析行为，不验证实际模型的回答质量。
- Memory 单测使用替身；额外三项用真实 Redis 7 验证成功压缩、空摘要和并发新增消息。临时 Redis 无宿主端口映射、不持久化、不接现有 Redis，测试后已清理。
- 所有源码/缓存/临时目录在 E 盘，现有 RootLens/EchoMind 服务没有重启，仍 healthy。

ChromaDB 0.5.23 与现有 posthog 的可选 telemetry 兼容噪声在测试中仍存在，不影响测试通过；本批不升级无关依赖或修改监控。测试容器无外网。

## 7. 重跑

使用已有 rootlens-echomind 镜像和 E 盘 pytest wheel 缓存。先启动无持久化临时 Redis，完整命令在 PowerShell 执行：

```powershell
cd E:\code\RootLens
docker run -d --rm --network none --name rootlens-batch2-test-redis redis:7-alpine redis-server --save '' --appendonly no
docker run --rm --network container:rootlens-batch2-test-redis --entrypoint python --mount 'type=bind,source=E:\code\RootLens\app,target=/workspace,readonly' --mount 'type=bind,source=E:\Codex\cache\pip\test-wheels,target=/wheels,readonly' --mount 'type=bind,source=E:\Codex\temp\rootlens-stage2-batch2,target=/test-temp' -w /workspace -e ROOTLENS_TEST_REDIS_URL=redis://127.0.0.1:6379/15 -e PYTHONDONTWRITEBYTECODE=1 -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 -e TMPDIR=/test-temp rootlens-echomind -c "import subprocess,sys; subprocess.run([sys.executable,'-m','pip','install','--no-index','--no-cache-dir','--find-links=/wheels','pytest==8.3.4'],check=True); sys.exit(subprocess.call([sys.executable,'-m','pytest','-q','--capture=sys','-p','no:cacheprovider','--basetemp=/test-temp/pytest','test_rootlens_first_slice.py','test_rootlens_evidence.py','test_rootlens_knowledge_memory.py']))"
docker stop rootlens-batch2-test-redis
```

源码只读挂载；临时 Redis 的网络本身无外网，因此测试容器也只可连接该 Redis。先确认名字未被其他用途占用，结束或失败后都应清理自己启动的临时容器。本机虚拟环境仍未完成依赖安装，以上不依赖它。

## 8. 尚未验证与下一步

未重建应用镜像，现有 /chat 仍是上一版本。未用真实第三方模型验证新 rewrite/rerank，未验证默认 MiniLM 的检索质量、增强 query 的 Recall 提升、知识/记忆隔离部署后生效或新镜像内容。

尚未接取证到 /chat、DiagnosisPipeline、证据领域评分、结构化诊断或真实端到端评测。旧 /eval/run 仍不能代表 Stage 2 完整链验收。

建议评审通过后进入第 3 批，只做共用管线和证据到路由/API 的衔接；第 4 批再 Docker 与真实 /chat 联调。本轮到此停止，不自动进入第 3 批。

学习时按这条线看：manifest 的文档来源 -> KnowledgeBase 的 upsert/search -> ToolResult 的阶段状态 -> rag_query 的来源约束 -> memory_options 与摘要保护。不必一次背下所有字段。
