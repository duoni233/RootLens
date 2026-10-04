import asyncio
import json
import math
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import chromadb
import pytest

from core.evidence import EvidenceBundle, QueryContext
from core.rag_query import EvidenceTerm, build_retrieval_query
from core.rootlens_config import ROOTLENS_COLLECTION, knowledge_collection, memory_options
from mcp.incident_tools import IncidentTools
from mcp.knowledge_base import KnowledgeBase
from mcp.tool_manager import MCPToolManager, Tool
from memory import conversation_memory as memory_module


class FixedEmbedding:
    """Controlled retrieval vectors, not a claim about production embedding quality."""
    def __call__(self, input):
        vectors = []
        for text in input:
            text = text.lower()
            counts = [sum(text.count(word) for word in words) for words in (
                ("dbconnectionerror", "connection pool exhausted", "db_pool_in_use"),
                ("5xx", "http 500", "application failure"),
                ("deployment", "release", "部署"),
                ("cpu", "traffic surge", "流量"),
            )]
            counts.append(1 if not any(counts) else 0)
            norm = math.sqrt(sum(n * n for n in counts))
            vectors.append([n / norm for n in counts])
        return vectors


@pytest.fixture
def knowledge(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"),
                                     settings=chromadb.Settings(anonymized_telemetry=False))
    kb = KnowledgeBase(client=client, collection_name=ROOTLENS_COLLECTION,
                       max_distance=0.8, embedding_function=FixedEmbedding())
    kb.load_rootlens_documents()
    return kb, client


def test_collection_isolation_no_customer_seeds_and_upsert(knowledge):
    kb, client = knowledge
    old = client.get_or_create_collection("knowledge_base", embedding_function=FixedEmbedding())
    old.add(ids=["original"], documents=["退款 发票 会员"], metadatas=[{"title": "原客服数据"}])
    count = kb.doc_count
    original = kb._collection.get(include=["documents", "metadatas"])
    second = KnowledgeBase(client=client, collection_name=ROOTLENS_COLLECTION,
                           embedding_function=FixedEmbedding())
    second.load_rootlens_documents()
    assert count == 4 == second.doc_count
    assert sorted(original["ids"]) == sorted(second._collection.get()["ids"])
    assert old.get()["documents"] == ["退款 发票 会员"]
    assert all("退款" not in text and "会员" not in text for text in original["documents"])
    assert {m["source_type"] for m in original["metadatas"]} == {"runbook", "historical_incident"}


@pytest.mark.parametrize("query,document", [
    ("DBConnectionError connection pool exhausted", "RL-RB-DB-001"),
    ("HTTP 500 5xx application failure", "RL-RB-APP-001"),
    ("deployment release 部署", "RL-RB-DEP-001"),
])
def test_correct_runbook_and_stable_source(knowledge, query, document):
    kb, _ = knowledge
    result = kb.search(query, top_k=1)
    assert result[0]["document_id"] == document
    assert result[0]["chunk_id"] == f"{document}:c0000"
    source = Path(__file__).parent / result[0]["source_ref"]
    assert source.is_file() and source.read_text(encoding="utf-8") == result[0]["content"]
    assert result[0]["metadata"]["evidence_category"] == "knowledge"


def test_unrelated_query_and_empty_collection_do_not_force_db(knowledge):
    kb, client = knowledge
    assert kb.search("园艺与花园种植") == []
    empty = KnowledgeBase(client=client, collection_name="rootlens_empty",
                          embedding_function=FixedEmbedding())
    assert empty.doc_count == 0 and empty.search("DBConnectionError") == []


def test_content_update_keeps_ids_and_removes_stale_chunks(knowledge):
    kb, _ = knowledge
    doc = {"document_id": "test-stable", "title": "test", "source_ref": "knowledge/test.md",
           "content": ("DBConnectionError。" * 100)}
    kb.add_documents([doc])
    assert len(kb._collection.get(where={"document_id": "test-stable"})["ids"]) > 1
    doc["content"] = "connection pool exhausted"
    kb.add_documents([doc])
    assert kb._collection.get(where={"document_id": "test-stable"})["ids"] == ["test-stable:c0000"]


def response(text, stop="end_turn"):
    return SimpleNamespace(content=[{"type": "text", "text": text}], stop_reason=stop)


@pytest.fixture
def manager():
    result = MCPToolManager(api_key="offline-test", base_url="https://api.deepseek.com/anthropic")
    result._client.messages.create = AsyncMock()
    yield result
    asyncio.run(result._client.close())


@pytest.mark.parametrize("text,stop,status", [
    ('```json\n["db pool", "connection timeout"]\n```', "end_turn", "performed"),
    ('[1, 2]', "end_turn", "failed"), ('[]', "end_turn", "failed"),
    ('{"answer":"not an array"}', "end_turn", "failed"),
    ('["db pool"]', "max_tokens", "failed"),
])
def test_rewrite_status_and_compatibility(manager, text, stop, status):
    manager._client.messages.create.return_value = response(text, stop)
    result = asyncio.run(manager.rewrite_query_result("original", n=2))
    assert result.status == status and result.data[0] == "original"
    assert manager._client.messages.create.call_args.kwargs["extra_body"] == {
        "thinking": {"type": "disabled"}}
    assert bool(result.error) == (status == "failed")


def test_rewrite_skip_and_exception_preserve_list_api(manager):
    result = asyncio.run(manager.rewrite_query_result("original", n=0))
    assert result.status == "skipped" and result.data == ["original"]
    manager._client.messages.create.assert_not_called()
    manager._client.messages.create.side_effect = RuntimeError("offline failure")
    result = asyncio.run(manager.rewrite_query_result("original"))
    assert result.status == "failed"
    assert asyncio.run(manager.rewrite_query("original")) == ["original"]


@pytest.mark.parametrize("text,stop,status", [
    ('[2,0,1]', "end_turn", "performed"),
    ('[0,0,1]', "end_turn", "failed"), ('[true,0,1]', "end_turn", "failed"),
    ('[3,0,1]', "end_turn", "failed"), ('[0]', "end_turn", "failed"),
    ('no array', "end_turn", "failed"), ('[2,0,1]', "max_tokens", "failed"),
])
def test_rerank_states_and_valid_permutation(manager, text, stop, status):
    manager._client.messages.create.return_value = response(text, stop)
    items = [{"content": str(i)} for i in range(3)]
    result = asyncio.run(manager.rerank_result("query", items, 1))
    assert result.status == status
    assert result.data == [items[2]] if status == "performed" else result.data == [items[0]]
    assert "extra_body" in manager._client.messages.create.call_args.kwargs


def test_rerank_skip_exception_and_list_compatibility(manager):
    assert asyncio.run(manager.rerank_result("q", [1], 2)).status == "skipped"
    manager._client.messages.create.assert_not_called()
    manager._client.messages.create.side_effect = RuntimeError("offline failure")
    assert asyncio.run(manager.rerank_result("q", [1, 2], 1)).status == "failed"
    assert asyncio.run(manager._rerank("q", [1, 2], 1)) == [1]


def test_rerank_prompt_contains_content_not_just_metadata(manager):
    manager._client.messages.create.return_value = response("[1,0]")
    items = [{"metadata": {"long": "x" * 1000}, "content": "connection pool exhausted"},
             {"metadata": {"long": "y" * 1000}, "content": "HTTP 500 failure"}]
    asyncio.run(manager.rerank_result("q", items, 1))
    prompt = manager._client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "connection pool exhausted" in prompt and "HTTP 500 failure" in prompt
    assert "x" * 1000 not in prompt


def register_search(manager, handler, fallback=None):
    manager.register(Tool(name="knowledge_search", description="test", handler=handler,
                          schema={"required": ["query"]}, supports_rerank=True,
                          cache_ttl=30, fallback=fallback))


def test_multi_query_dedup_ignores_score_and_records_stages(manager):
    manager._client.messages.create.side_effect = [response('["alt"]'), response('[1,0]')]

    async def search(params, ctx):
        return [{"chunk_id": "a", "collection": "rootlens", "content": "a",
                 "score": 0.8 if params["query"] == "original" else 0.6},
                {"chunk_id": "b", "content": "b"}]

    register_search(manager, search)
    result = asyncio.run(manager.search_with_rewrite("knowledge_search", "original", top_k=1))
    assert result.success and result.reranked and result.data[0]["chunk_id"] == "b"
    assert (result.rewrite_status, result.retrieval_status, result.rerank_status) == (
        "performed", "performed", "performed")
    assert not result.stage_errors


def test_empty_and_fallback_are_not_knowledge_hits(manager):
    async def empty(params, ctx):
        return []

    register_search(manager, empty)
    result = asyncio.run(manager.search_with_rewrite("knowledge_search", "q", rewrite_enabled=False))
    assert result.success and result.data == [] and result.retrieval_status == "performed"

    async def broken(params, ctx):
        raise RuntimeError("search unavailable")

    register_search(manager, broken, fallback=lambda *args: [{"fallback": True, "content": "generic"}])
    manager._cache.clear()
    result = asyncio.run(manager.search_with_rewrite("knowledge_search", "q", rewrite_enabled=False))
    assert not result.success and not result.data and result.retrieval_status == "failed"


def test_partial_retrieval_and_rerank_failure_are_distinct(manager):
    manager._client.messages.create.side_effect = [response('["bad"]'), response('invalid JSON')]

    async def search(params, ctx):
        if params["query"] == "bad":
            raise RuntimeError("partial retrieval failure")
        return [{"chunk_id": "a"}, {"chunk_id": "b"}]

    register_search(manager, search)
    result = asyncio.run(manager.search_with_rewrite("knowledge_search", "original", top_k=1))
    assert result.success and result.retrieval_status == "degraded"
    assert result.rerank_status == "failed" and not result.reranked
    assert set(result.stage_errors) == {"retrieval", "rerank"}


def test_cached_rerank_failure_stays_failed(manager):
    async def search(params, ctx):
        return [1, 2]

    register_search(manager, search)
    manager._client.messages.create.return_value = response("invalid")
    first = asyncio.run(manager.call("knowledge_search", {"query": "q"}, rerank_top_k=1))
    second = asyncio.run(manager.call("knowledge_search", {"query": "q"}, rerank_top_k=1))
    assert second.cached and not second.reranked
    assert first.rerank_status == second.rerank_status == "failed"
    assert first.stage_errors == second.stage_errors


def test_disabled_stages_are_skipped_and_not_called(manager):
    async def search(params, ctx):
        return [{"chunk_id": "a"}, {"chunk_id": "b"}]
    register_search(manager, search)
    result = asyncio.run(manager.search_with_rewrite("knowledge_search", "q", top_k=1,
                                                   rewrite_enabled=False, rerank_enabled=False))
    assert (result.rewrite_status, result.rerank_status) == ("skipped", "skipped")
    assert not result.reranked
    manager._client.messages.create.assert_not_called()


def test_knowledge_loader_rejects_evaluation_path(knowledge, tmp_path):
    kb, _ = knowledge
    root = tmp_path / "knowledge"
    root.mkdir()
    outside = tmp_path / "evaluation.md"
    outside.write_text("must not read evaluation", encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps([{
        "file": "../evaluation.md", "document_id": "evil", "title": "evil",
        "source_type": "runbook", "service_name": "general", "published_at": "2026-08-01",
    }]), encoding="utf-8")
    before = kb.doc_count
    with pytest.raises(ValueError):
        kb.load_rootlens_documents(root)
    assert kb.doc_count == before


def bundle():
    tools = IncidentTools()
    ctx = QueryContext.build(service_name="payment-service", environment="demo",
                             anchor_time="2026-09-01T10:05:00+08:00", timezone="Asia/Shanghai",
                             dataset_id=tools.manifest.dataset_id,
                             dataset_version=tools.manifest.dataset_version)
    from mcp.tool_manager import ToolResult
    data = asyncio.run(tools.query_logs(ctx.tool_params("query_logs")))
    return EvidenceBundle.from_results(ctx, {"query_logs": ToolResult(True, data, "query_logs")})


def test_evidence_terms_change_retrieval_without_mutating_message(knowledge):
    kb, _ = knowledge
    original = "payment-service 10:05 开始 5xx 激增"
    evidence = bundle()
    log = next(item for item in evidence.evidence if item.record_id == "L001")
    terms = [EvidenceTerm("DBConnectionError", log.evidence_id),
             EvidenceTerm("connection pool exhausted", log.evidence_id),
             EvidenceTerm("DBConnectionError", log.evidence_id)]
    result = build_retrieval_query(original, evidence=evidence, terms=terms)
    assert result.original_message == original and result.query.count("DBConnectionError") == 1
    assert result.evidence_ids == [log.evidence_id]
    assert kb.search(original, 1)[0]["document_id"] == "RL-RB-APP-001"
    assert kb.search(result.query, 1)[0]["document_id"] == "RL-RB-DB-001"


def test_unproven_terms_and_no_evidence_fall_back():
    original = "runbook query"
    evidence = bundle()
    result = build_retrieval_query(original, evidence=evidence,
                                  terms=[EvidenceTerm("expected_diagnosis", "missing"),
                                         EvidenceTerm("a guessed root cause", evidence.evidence[0].evidence_id)])
    assert result.query == original and not result.evidence_ids
    assert build_retrieval_query(original).query == original


def test_expected_file_cannot_influence_enrichment_or_knowledge(knowledge, tmp_path, monkeypatch):
    kb, _ = knowledge
    expected = tmp_path / "evaluation" / "expected.json"
    expected.parent.mkdir()
    expected.write_text('{"expected_diagnosis":"answer A"}')
    real_open = Path.open

    def guarded(path, *args, **kwargs):
        if "evaluation" in path.parts:
            raise AssertionError("knowledge must not read evaluation")
        return real_open(path, *args, **kwargs)

    def lookup():
        with monkeypatch.context() as patch:
            patch.setattr(Path, "open", guarded)
            kb.load_rootlens_documents()
            query = build_retrieval_query("payment-service 5xx", evidence=bundle())
            return query, kb.search(query.query)

    before = lookup()
    expected.write_text('{"expected_diagnosis":"answer B"}')
    assert lookup() == before


class FakeRedis:
    def __init__(self):
        self.lists, self.values, self.ttls = {}, {}, {}
        self.watch_failure = False

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    async def expire(self, key, value):
        self.ttls[key] = value

    async def llen(self, key):
        return len(self.lists.get(key, []))

    async def lrange(self, key, start, end):
        return list(self.lists.get(key, []))[start:None if end == -1 else end + 1]

    async def get(self, key):
        return self.values.get(key)

    def pipeline(self, **kwargs):
        return FakePipeline(self)

    async def aclose(self):
        pass


class FakePipeline:
    def __init__(self, redis):
        self.redis, self.commands = redis, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def watch(self, *keys):
        pass

    async def lrange(self, *args):
        return await self.redis.lrange(*args)

    async def get(self, *args):
        return await self.redis.get(*args)

    def multi(self):
        pass

    def setex(self, key, ttl, value):
        self.commands.append(("set", key, ttl, value))

    def ltrim(self, key, start, end):
        self.commands.append(("trim", key, start, end))

    def expire(self, key, ttl):
        self.commands.append(("expire", key, ttl))

    async def execute(self):
        if self.redis.watch_failure:
            raise memory_module.redis.WatchError()
        for op, key, *args in self.commands:
            if op == "set":
                self.redis.values[key], self.redis.ttls[key] = args[1], args[0]
            elif op == "trim":
                self.redis.lists[key] = self.redis.lists[key][args[0]:args[1] + 1]
            else:
                self.redis.ttls[key] = args[0]


@pytest.fixture
def memory(monkeypatch):
    store = FakeRedis()
    chroma = Mock()
    chroma.get_or_create_collection.return_value = Mock()
    monkeypatch.setattr(memory_module.redis, "from_url", lambda *args, **kwargs: store)
    monkeypatch.setattr(memory_module.chromadb, "HttpClient", lambda **kwargs: chroma)
    monkeypatch.delenv("ROOTLENS_USER_PROFILE_ENABLED", raising=False)
    monkeypatch.delenv("ROOTLENS_EPISODIC_RECALL_ENABLED", raising=False)
    result = memory_module.MemoryManager(api_key="offline-test",
        base_url="https://api.deepseek.com/anthropic", **memory_options())
    result._client.messages.create = AsyncMock(return_value=response("summary"))
    yield result, store, chroma
    asyncio.run(result._client.close())


def add_messages(memory, count):
    original = memory.COMPRESS_AT
    memory.COMPRESS_AT = 1000
    for i in range(count):
        asyncio.run(memory.add_message("u", "c", memory_module.MsgRole.USER, str(i)))
    memory.COMPRESS_AT = original


def test_memory_defaults_and_current_redis_context(memory):
    manager, store, chroma = memory
    assert not manager.enable_user_profile and not manager.enable_episodic_recall
    chroma.get_or_create_collection.assert_called_once_with("episodic")
    manager._search_episodic = AsyncMock(side_effect=AssertionError("disabled"))
    manager._get_profile = AsyncMock(side_effect=AssertionError("disabled"))
    add_messages(manager, 2)
    ctx = asyncio.run(manager.get_context("u", "c", "query"))
    assert [m.content for m in ctx.recent_messages] == ["0", "1"]
    assert not ctx.user_profile and not ctx.relevant_history
    assert store.ttls[manager._wm_key("u", "c")] == 86400
    assert not asyncio.run(manager.get_context("u", "another")).recent_messages
    asyncio.run(manager.update_profile("u", "c"))
    manager._client.messages.create.assert_not_called()


@pytest.mark.parametrize("kind", ["exception", "empty", "truncated", "watch_failure", "new_message"])
def test_summary_failure_or_concurrency_preserves_messages(memory, kind):
    manager, store, _ = memory
    add_messages(manager, 25)
    key = manager._wm_key("u", "c")
    snapshot = list(store.lists[key])
    if kind == "exception":
        manager._client.messages.create.side_effect = RuntimeError("no summary")
    elif kind == "empty":
        manager._client.messages.create.return_value = response("")
    elif kind == "truncated":
        manager._client.messages.create.return_value = response("incomplete", "max_tokens")
    elif kind == "watch_failure":
        store.watch_failure = True
    else:
        async def new_message(**kwargs):
            await store.lpush(key, json.dumps({"role": "user", "content": "concurrent",
                                              "ts": "2026-09-01T10:06:00", "metadata": {}}))
            return response("summary")
        manager._client.messages.create.side_effect = new_message
    asyncio.run(manager._compress("u", "c"))
    assert store.lists[key][-25:] == snapshot
    assert manager._summary_key("u", "c") not in store.values


def test_successful_summary_keeps_latest_five_and_uses_compatibility(memory):
    manager, store, _ = memory
    add_messages(manager, 25)
    asyncio.run(manager._compress("u", "c"))
    ctx = asyncio.run(manager.get_context("u", "c"))
    assert [m.content for m in ctx.recent_messages] == ["20", "21", "22", "23", "24"]
    assert ctx.summary == "summary"
    kwargs = manager._client.messages.create.call_args.kwargs
    assert "user: 0" in kwargs["messages"][0]["content"]
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    manager._episodic.add.assert_called_once()


def test_config_explicit_opt_in_and_invalid_collection(monkeypatch):
    monkeypatch.setenv("ROOTLENS_USER_PROFILE_ENABLED", "true")
    monkeypatch.setenv("ROOTLENS_EPISODIC_RECALL_ENABLED", "1")
    assert all(memory_options().values())
    monkeypatch.setenv("ROOTLENS_USER_PROFILE_ENABLED", "typo")
    with pytest.raises(ValueError):
        memory_options()
    monkeypatch.setenv("ROOTLENS_KNOWLEDGE_COLLECTION", "knowledge_base")
    with pytest.raises(ValueError):
        knowledge_collection()


def test_api_context_excludes_fallback_and_reports_sources(monkeypatch):
    from api import main
    from mcp.tool_manager import ToolResult
    fake = SimpleNamespace(search_with_rewrite=AsyncMock(return_value=ToolResult(
        success=True, data=[{"fallback": True, "content": "generic fallback"}],
        tool_name="knowledge_search")))
    monkeypatch.setattr(main, "_tool_manager", fake)
    assert asyncio.run(main._build_knowledge_context("runbook query")) == ("", False)
    fake.search_with_rewrite.return_value.data = [{"chunk_id": "id", "source_ref": "knowledge/x.md",
                                                  "title": "test", "content": "rule"}]
    text, used = asyncio.run(main._build_knowledge_context("runbook query"))
    assert used and "knowledge/x.md" in text and "现场事实" in text


@pytest.mark.parametrize("scenario", ["success", "empty", "concurrent"])
def test_real_redis_compression_transaction(scenario):
    url = os.getenv("ROOTLENS_TEST_REDIS_URL")
    if not url:
        pytest.skip("isolated Redis test service not configured")

    async def run():
        manager = memory_module.MemoryManager.__new__(memory_module.MemoryManager)
        manager._redis = memory_module.redis.from_url(url, decode_responses=True)
        manager._model = "offline-model"
        manager.enable_user_profile = manager.enable_episodic_recall = False
        manager._store_episodic = AsyncMock()
        user, conv = "batch2-" + uuid.uuid4().hex, "transaction-test"
        key, summary_key = manager._wm_key(user, conv), manager._summary_key(user, conv)

        async def summarize(**kwargs):
            if scenario == "concurrent":
                old_threshold = manager.COMPRESS_AT
                manager.COMPRESS_AT = 1000
                await manager.add_message(user, conv, memory_module.MsgRole.USER, "concurrent")
                manager.COMPRESS_AT = old_threshold
            return response("" if scenario == "empty" else "valid summary")

        manager._client = SimpleNamespace(base_url="https://api.deepseek.com/anthropic",
            messages=SimpleNamespace(create=AsyncMock(side_effect=summarize)))
        try:
            manager.COMPRESS_AT = 1000
            for i in range(16):
                await manager.add_message(user, conv, memory_module.MsgRole.USER, str(i))
            manager.COMPRESS_AT = 15
            await manager._compress(user, conv)
            if scenario == "success":
                assert await manager._redis.llen(key) == 5
                assert await manager._redis.get(summary_key) == "valid summary"
                recent = await manager._get_working_memory(user, conv)
                assert [m.content for m in recent] == ["11", "12", "13", "14", "15"]
                assert await manager._redis.ttl(key) > 0
            else:
                assert await manager._redis.llen(key) == (17 if scenario == "concurrent" else 16)
                assert await manager._redis.get(summary_key) is None
        finally:
            await manager._redis.delete(key, summary_key)
            await manager._redis.aclose()

    asyncio.run(run())
