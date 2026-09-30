import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import chromadb

from agents.agent_orchestrator import AgentOrchestrator, AgentResponse, AgentType
from core.evidence import build_query_context
from core.diagnosis_pipeline import DiagnosisPipeline, KnowledgeResult
from core.evidence import EvidenceBundle, QueryContext
from core.intent_recognizer import IntentCategory, IntentResult, UrgencyLevel
from core.routing_signals import extract_routing_signals
from mcp.incident_tools import IncidentTools
from mcp.tool_manager import MCPToolManager, ToolResult
from mcp.tool_manager import RAGStageResult, Tool
from mcp.knowledge_base import KnowledgeBase


MESSAGE = "payment-service 10:05 开始 5xx 激增"
FULL_MESSAGE = "payment-service 从 10:05 开始 5xx 激增，刚发布 v2.3.7，日志里有 DBConnectionError"


def recognized(message=MESSAGE, intent=IntentCategory.SERVICE_INCIDENT, *, entities=None):
    values = ({"service_name": ["payment-service"], "start_time": ["10:05"],
               "status_code": ["5xx"]} if entities is None else entities)
    return IntentResult(intent=intent, confidence=0.9, urgency=UrgencyLevel.MEDIUM,
                        intent_group="application", entities=values, reasoning="test",
                        latency_ms=1.0)


@pytest.fixture
def setup_pipeline():
    manager = MCPToolManager(api_key="test-key", base_url="https://example.invalid")
    incident = IncidentTools()
    incident.register(manager, cache_ttl=0)
    orchestrator = AgentOrchestrator(api_key="test-key", base_url="https://example.invalid")
    requests = []

    async def execute(req, agent_type):
        requests.append((req, agent_type))
        return AgentResponse(agent_type=agent_type, content="基于证据的待验证诊断", success=True)

    orchestrator._execute = execute
    queries = []

    async def lookup(query):
        queries.append(query)
        return KnowledgeResult(text="[知识] Runbook 是处置规则，不是现场事实", used=True,
                               stages={"rewrite": "performed", "retrieval": "performed",
                                       "rerank": "skipped"})

    pipeline = DiagnosisPipeline(
        orchestrator=orchestrator, tool_manager=manager, knowledge_lookup=lookup,
        dataset_id=incident.manifest.dataset_id,
        dataset_version=incident.manifest.dataset_version,
        timezone=incident.manifest.timezone,
    )
    return pipeline, manager, orchestrator, requests, queries


def run(pipeline, message=MESSAGE, intent=None, **kwargs):
    return asyncio.run(pipeline.run(
        message=message, user_id="u", conv_id="c", memory_context="", history=None,
        intent_result=intent or recognized(message), **kwargs,
    ))


def test_short_report_acquires_evidence_and_routes_once(setup_pipeline):
    pipeline, _, orchestrator, requests, queries = setup_pipeline
    route = orchestrator._route_decision
    decisions = []

    def counted(req):
        decisions.append(req)
        return route(req)

    orchestrator._route_decision = counted
    outcome = run(pipeline)
    assert outcome.result.primary_agent == AgentType.APPLICATION
    assert outcome.result.supporting_agents == [AgentType.DATABASE]
    assert all(state.status == "ok" for state in outcome.bundle.tool_status.values())
    assert any(item.attributes.error_code == "DBConnectionError"
               for item in outcome.bundle.evidence if item.source_type == "log")
    assert any(item.attributes.version == "v2.3.7"
               for item in outcome.bundle.evidence if item.source_type == "deployment")
    assert "DBConnectionError" in queries[0] and "connection pool exhausted" in queries[0]
    assert requests and all(req is requests[0][0] for req, _ in requests)
    assert len(decisions) == 1
    assert "现场事实" in requests[0][0].evidence_context
    assert "DBConnectionError" in requests[0][0].evidence_context
    assert "Runbook" in requests[0][0].context
    assert requests[0][0].message == MESSAGE
    assert requests[0][0].entities == recognized().entities
    assert requests[0][0].evidence_entities["error_code"] == ["DBConnectionError", "HTTP500"]
    assert len(outcome.signals.evidence_ids["database"]) >= 1
    assert "2026-09-01" in outcome.bundle.query_context.assumptions[-1]
    assert "发布先于故障不等于发布是根因" in requests[0][0].evidence_context


def test_evidence_derived_code_activates_supporting_agent_skill(setup_pipeline):
    from core.skill_loader import SkillManager

    pipeline, _, orchestrator, requests, _ = setup_pipeline
    manager = SkillManager(root_dir=str(Path(__file__).parent / "skills"))
    manager.load()
    orchestrator.set_skill_manager(manager)
    outcome = run(pipeline)
    database_request = next(req for req, agent in requests if agent == AgentType.DATABASE)
    prompt = orchestrator._pool[AgentType.DATABASE][0]._build_system_prompt(database_request)
    assert "数据库故障诊断" in prompt
    assert outcome.result.supporting_agents == [AgentType.DATABASE]
    assert database_request.message == MESSAGE


def test_full_stage_one_request_still_routes_to_application_and_database(setup_pipeline):
    pipeline, _, _, _, _ = setup_pipeline
    from core.intent_recognizer import IntentRecognizer
    entities = IntentRecognizer(api_key="test-key")._extract_entities(FULL_MESSAGE)
    outcome = run(pipeline, FULL_MESSAGE, recognized(FULL_MESSAGE, entities=entities))
    assert outcome.result.primary_agent == AgentType.APPLICATION
    assert AgentType.DATABASE in outcome.result.supporting_agents
    assert entities["version"] == ["v2.3.7"]


def test_runbook_query_skips_operational_tools(setup_pipeline, monkeypatch):
    pipeline, manager, _, requests, queries = setup_pipeline
    call = AsyncMock(side_effect=AssertionError("operational tool must not run"))
    monkeypatch.setattr(manager, "call", call)
    outcome = run(pipeline, "查连接池故障 Runbook",
                  recognized(intent=IntentCategory.RUNBOOK_QUERY, entities={}))
    call.assert_not_awaited()
    assert outcome.bundle is None and queries == ["查连接池故障 Runbook"]
    assert len(requests) == 1


@pytest.mark.parametrize("entities,environment", [
    ({"start_time": ["10:05"]}, None),
    ({"service_name": ["payment-service"], "start_time": ["10:05"]}, "prod"),
    ({"service_name": ["payment-service"]}, None),
])
def test_missing_conditions_clarify_without_tool_or_agent(setup_pipeline, monkeypatch,
                                                           entities, environment):
    pipeline, manager, _, requests, queries = setup_pipeline
    call = AsyncMock(side_effect=AssertionError("must not scan"))
    monkeypatch.setattr(manager, "call", call)
    outcome = run(pipeline, intent=recognized(entities=entities), environment=environment)
    assert outcome.clarification_required and outcome.result.agent_types == []
    assert outcome.bundle is None and not requests and not queries
    call.assert_not_awaited()


def test_explicit_complete_time_has_no_demo_date_assumption(setup_pipeline):
    pipeline, _, _, _, _ = setup_pipeline
    outcome = run(pipeline, environment="prod",
                  anchor_time=datetime.fromisoformat("2026-09-01T10:05:00+08:00"))
    assert not outcome.clarification_required
    assert outcome.bundle.query_context.environment == "prod"
    assert outcome.bundle.query_context.assumptions == []
    assert all(item.environment == "prod" for item in outcome.bundle.evidence)


def test_conflicting_explicit_and_message_time_requires_clarification(setup_pipeline):
    pipeline, _, _, requests, queries = setup_pipeline
    outcome = run(pipeline, anchor_time=datetime.fromisoformat("2026-09-01T11:05:00+08:00"))
    assert outcome.clarification_required and "不一致" in outcome.result.response
    assert not requests and not queries


def test_chinese_date_resolves_without_demo_date_guess():
    query, error = build_query_context(
        entities={"service_name": ["payment-service"], "start_time": ["10:05"],
                  "date": ["2026年9月1日"]}, environment="prod", message="",
    )
    assert error is None and query.environment == "prod"
    assert query.anchor_time.isoformat() == "2026-09-01T10:05:00+08:00"


def test_insufficient_alert_does_not_acquire(setup_pipeline, monkeypatch):
    pipeline, manager, _, _, _ = setup_pipeline
    call = AsyncMock(side_effect=AssertionError("must not acquire"))
    monkeypatch.setattr(manager, "call", call)
    outcome = run(pipeline, "payment-service 10:05 需要协助",
                  recognized(intent=IntentCategory.ALERT_TRIAGE,
                             entities={"service_name": ["payment-service"],
                                       "start_time": ["10:05"]}))
    assert outcome.bundle is None
    assert outcome.clarification_required and "具体" in outcome.result.response
    call.assert_not_awaited()


def test_alert_with_service_time_and_event_acquires(setup_pipeline):
    pipeline, _, _, _, _ = setup_pipeline
    outcome = run(pipeline, "payment-service 10:05 告警 5xx",
                  recognized(intent=IntentCategory.ALERT_TRIAGE))
    assert outcome.bundle is not None
    assert outcome.result.primary_agent == AgentType.APPLICATION
    assert AgentType.DATABASE in outcome.result.supporting_agents


@pytest.mark.parametrize("tool_name,status", [
    ("query_logs", "empty"), ("query_logs", "failed"), ("query_logs", "degraded"),
])
def test_partial_tool_states_do_not_become_facts(setup_pipeline, monkeypatch,
                                                   tool_name, status):
    pipeline, manager, _, requests, queries = setup_pipeline
    original = manager.call

    async def changed(name, params):
        if name != tool_name:
            return await original(name, params)
        if status == "empty":
            return ToolResult(success=True, data=[], tool_name=name)
        if status == "failed":
            return ToolResult(success=False, data=None, tool_name=name, error="unavailable")
        return ToolResult(success=True, data=[{"fake": "DBConnectionError"}],
                          tool_name=name, error="fallback")

    monkeypatch.setattr(manager, "call", changed)
    outcome = run(pipeline)
    assert outcome.bundle.tool_status[tool_name].status == status
    assert not any(item.source_type == "log" for item in outcome.bundle.evidence)
    assert "database" not in outcome.signals.floors
    assert "DBConnectionError" not in queries[0]
    assert f"{tool_name}={status}" in requests[0][0].evidence_context


def test_duplicate_logs_are_deduped_and_floor_does_not_accumulate(setup_pipeline, monkeypatch):
    pipeline, manager, orchestrator, requests, _ = setup_pipeline
    original = manager.call

    async def duplicated(name, params):
        result = await original(name, params)
        if name == "query_logs":
            return ToolResult(success=True, data=result.data * 10, tool_name=name)
        return result

    monkeypatch.setattr(manager, "call", duplicated)
    outcome = run(pipeline)
    assert outcome.signals.floors["database"] == 0.55
    ids = [item.evidence_id for item in outcome.bundle.evidence]
    assert len(ids) == len(set(ids))
    assert requests[0][0].routing_signals["database"] == 0.55
    assert orchestrator._domain_scores(requests[0][0])[AgentType.DATABASE] == 0.55


def test_knowledge_only_cannot_create_domain_signal(setup_pipeline):
    pipeline, _, _, _, _ = setup_pipeline
    bundle = run(pipeline).bundle
    knowledge = SimpleNamespace(evidence_category="knowledge", source_type="log",
                                attributes=SimpleNamespace(error_code="DBConnectionError"))
    forged = bundle.model_copy(update={"evidence": [knowledge]})
    assert extract_routing_signals(forged).floors == {}


def test_expected_file_does_not_enter_pipeline(setup_pipeline, tmp_path, monkeypatch):
    pipeline, manager, _, _, _ = setup_pipeline
    runtime = tmp_path / "runtime"
    shutil.copytree(Path(__file__).parent / "datasets" / "runtime", runtime)
    expected = tmp_path / "evaluation" / "INC-001.expected.json"
    expected.parent.mkdir()
    expected.write_text(json.dumps({"expected_diagnosis": "SECRET-A"}), encoding="utf-8")
    private = IncidentTools(runtime_root=runtime)
    private.register(manager, cache_ttl=0)
    first = run(pipeline)
    expected.write_text(json.dumps({"expected_diagnosis": "SECRET-B"}), encoding="utf-8")
    second = run(pipeline)
    assert [item.evidence_id for item in first.bundle.evidence] == [
        item.evidence_id for item in second.bundle.evidence]
    assert "SECRET-" not in str(first.bundle) + str(second.bundle)


def test_evidence_query_reaches_rootlens_collection(setup_pipeline, tmp_path, monkeypatch):
    from api import main

    class Embedding:
        def __call__(self, input):
            vectors = []
            for value in input:
                text = value.lower()
                scores = [sum(text.count(word) for word in words) for words in (
                    ("dbconnectionerror", "connection pool exhausted", "db_pool_in_use"),
                    ("5xx", "http 500", "application failure"),
                    ("deployment", "release", "部署"),
                    ("cpu", "traffic surge"),
                )]
                scores.append(1 if not any(scores) else 0)
                magnitude = sum(score * score for score in scores) ** 0.5
                vectors.append([score / magnitude for score in scores])
            return vectors

    pipeline, manager, _, _, _ = setup_pipeline
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"),
                                      settings=chromadb.Settings(anonymized_telemetry=False))
    kb = KnowledgeBase(client=client, collection_name="rootlens_runbooks_v1",
                       max_distance=0.8, embedding_function=Embedding())
    kb.load_rootlens_documents()
    manager.register(Tool(name="knowledge_search", description="RootLens Runbooks",
                          handler=kb.search_handler, schema={"type": "object", "properties": {
                              "query": {"type": "string"}, "top_k": {"type": "integer"}},
                              "required": ["query"]}, supports_rerank=False))
    manager.rewrite_query_result = AsyncMock(side_effect=lambda query, n: RAGStageResult(
        [query], "skipped"))
    monkeypatch.setattr(main, "_tool_manager", manager)
    pipeline.knowledge_lookup = main._retrieve_knowledge_context
    outcome = run(pipeline)
    assert outcome.knowledge.used
    assert "db-connection-pool.md" in outcome.knowledge.text
    assert any(source.document_id == "RL-RB-DB-001" and
               source.source_ref.endswith("db-connection-pool.md")
               for source in outcome.knowledge.sources)
    assert outcome.knowledge.stages == {"rewrite": "skipped", "retrieval": "performed",
                                        "rerank": "skipped"}


def test_rag_fallback_text_is_not_a_knowledge_hit(monkeypatch):
    from api import main

    manager = SimpleNamespace(search_with_rewrite=AsyncMock(return_value=ToolResult(
        success=True, data=[{"title": "fallback", "content": "DBConnectionError",
                             "fallback": True}], tool_name="knowledge_search",
        rewrite_status="failed", retrieval_status="degraded", rerank_status="skipped",
        error="retrieval unavailable")))
    monkeypatch.setattr(main, "_tool_manager", manager)
    result = asyncio.run(main._retrieve_knowledge_context(MESSAGE))
    assert not result.used and not result.text
    assert result.stages["retrieval"] == "degraded"


def test_http_chat_exposes_stage_three_contract(setup_pipeline, monkeypatch):
    from api import main

    pipeline, _, orchestrator, _, _ = setup_pipeline
    orchestrator.recognize_intent = AsyncMock(return_value=recognized())
    memory = SimpleNamespace(
        get_context=AsyncMock(return_value=SimpleNamespace(
            recent_messages=[], to_prompt_text=lambda: "")),
        add_message=AsyncMock(), enable_user_profile=False,
    )
    monkeypatch.setattr(main, "_orchestrator", orchestrator)
    monkeypatch.setattr(main, "_memory", memory)
    monkeypatch.setattr(main, "_diagnosis_pipeline", pipeline)

    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                    base_url="http://test") as client:
            return await client.post("/chat", json={"message": MESSAGE})

    response = asyncio.run(request())
    assert response.status_code == 200
    body = response.json()
    assert body["primary_agent"] == "application"
    assert body["supporting_agents"] == ["database"]
    assert body["tool_status"] == {name: "ok" for name in (
        "query_logs", "query_metrics", "query_deployments")}
    assert body["evidence_ids"] and body["knowledge_used"]
    assert body["rag_stage_status"]["retrieval"] == "performed"
    assert body["query_context"]["environment"] == "demo"
    assert body["routing_signal_sources"]["database"]
    assert memory.add_message.await_count == 2
