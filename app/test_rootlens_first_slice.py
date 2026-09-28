import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

if importlib.util.find_spec("anthropic") is None:
    anthropic = types.ModuleType("anthropic")

    class AsyncAnthropic:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    anthropic.AsyncAnthropic = AsyncAnthropic
    sys.modules["anthropic"] = anthropic

from agents.agent_orchestrator import AgentOrchestrator, AgentResponse, AgentType, Request
from core.intent_recognizer import IntentCategory, IntentRecognizer, UrgencyLevel
from core.skill_loader import SkillManager
from core.llm_utils import non_thinking_options


MVP = (
    "payment-service 从 10:05 开始 5xx 激增，刚发布 v2.3.7，"
    "日志里有 DBConnectionError，帮我判断原因"
)


def make_request(message, intent, entities=None, urgency=UrgencyLevel.LOW, confidence=0.9):
    return Request(
        message=message,
        user_id="test-user",
        conv_id="test-conv",
        intent=intent,
        intent_group=intent.value,
        entities=entities or {},
        urgency=urgency,
        intent_confidence=confidence,
    )


@pytest.fixture
def orchestrator():
    return AgentOrchestrator(api_key="test-key", base_url="https://example.invalid")


@pytest.fixture
def recognizer():
    return IntentRecognizer(api_key="test-key", base_url="https://example.invalid")


def test_mvp_entities_pattern_and_route(recognizer, orchestrator):
    assert recognizer._pattern_recognize(MVP)["intent"] == IntentCategory.SERVICE_INCIDENT
    entities = recognizer._extract_entities(MVP)
    assert entities["service_name"] == ["payment-service"]
    assert entities["start_time"] == ["10:05"]
    assert entities["version"] == ["v2.3.7"]
    assert entities["status_code"] == ["5xx"]
    assert entities["error_code"] == ["DBConnectionError"]

    decision = orchestrator._route_decision(
        make_request(MVP, IntentCategory.SERVICE_INCIDENT, entities)
    )
    assert decision.primary_agent == AgentType.APPLICATION
    assert decision.supporting_agents == [AgentType.DATABASE]


@pytest.mark.parametrize(
    ("message", "intent", "expected"),
    [
        ("数据库出现慢查询", IntentCategory.DATABASE_ISSUE, AgentType.DATABASE),
        ("order-service 返回 500", IntentCategory.SERVICE_INCIDENT, AgentType.APPLICATION),
        ("节点 CPU 使用率升高", IntentCategory.RESOURCE_ISSUE, AgentType.INFRASTRUCTURE),
        ("查询这个告警的 runbook", IntentCategory.RUNBOOK_QUERY, AgentType.GENERAL),
    ],
)
def test_single_domain_routing(orchestrator, message, intent, expected):
    decision = orchestrator._route_decision(make_request(message, intent))
    assert decision.primary_agent == expected
    assert decision.supporting_agents == []


def test_clarification_asks_for_incident_evidence(orchestrator):
    req = make_request("这个有问题", IntentCategory.OTHER, confidence=0.2)
    result = asyncio.run(orchestrator.run(req))
    assert result.primary_agent == AgentType.GENERAL
    assert "服务" in result.response
    assert "订单" not in result.response


def test_p1_keeps_diagnosis_and_marks_escalation(orchestrator, recognizer):
    message = "P1：payment-service 不可用，日志有 DBConnectionError"
    entities = recognizer._extract_entities(message)
    req = make_request(
        message, IntentCategory.SERVICE_INCIDENT, entities, UrgencyLevel.CRITICAL
    )
    called = []

    async def fake_execute(request, agent_type):
        called.append(agent_type)
        return AgentResponse(agent_type=agent_type, content="待验证的诊断", success=True)

    orchestrator._execute = fake_execute
    result = asyncio.run(orchestrator.run(req))
    assert result.primary_agent == AgentType.APPLICATION
    assert AgentType.APPLICATION in called
    assert result.escalated is True


def test_skills_match_new_agents_without_customer_service_rules():
    manager = SkillManager(str(Path(__file__).parent / "skills"))
    manager.load()
    assert manager.errors == []
    assert len(manager.skills) == 4
    assert all(skill.enabled for skill in manager.skills)
    assert "应用服务故障诊断" in manager.prompt_for(MVP, "application")
    assert "数据库故障诊断" in manager.prompt_for(MVP, "database")
    assert manager.prompt_for(MVP, "infrastructure") == ""
    assert "退款" not in manager.prompt_for(MVP, "database")


def test_agent_system_prompt_receives_matching_skill(orchestrator, recognizer):
    manager = SkillManager(str(Path(__file__).parent / "skills"))
    manager.load()
    orchestrator.set_skill_manager(manager)
    req = make_request(MVP, IntentCategory.SERVICE_INCIDENT, recognizer._extract_entities(MVP))
    application = orchestrator._pool[AgentType.APPLICATION][0]
    database = orchestrator._pool[AgentType.DATABASE][0]
    assert "应用服务故障诊断" in application._build_system_prompt(req)
    assert "数据库故障诊断" in database._build_system_prompt(req)


def test_recognizer_final_result_with_controlled_llm(recognizer):
    async def fake_llm(message, history):
        return {"intent": IntentCategory.SERVICE_INCIDENT, "confidence": 0.9}

    recognizer._llm_recognize = fake_llm
    result = asyncio.run(recognizer.recognize(MVP))
    assert result.intent == IntentCategory.SERVICE_INCIDENT
    assert result.urgency == UrgencyLevel.HIGH
    assert result.entities["service_name"] == ["payment-service"]
    assert result.source_scores["llm"] == 0.9


@pytest.mark.parametrize(
    "base_url",
    ["https://api.anthropic.com", "https://example.invalid", "https://api.deepseek.com.example.invalid"],
)
def test_other_providers_do_not_receive_deepseek_options(base_url):
    assert non_thinking_options(types.SimpleNamespace(base_url=base_url)) == {}


def test_intent_call_disables_deepseek_thinking(recognizer):
    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(
            stop_reason="end_turn",
            usage=types.SimpleNamespace(output_tokens=50),
            content=[{"type": "text", "text": '{"intent":"service_incident","confidence":0.9}'}],
        )

    recognizer.client = types.SimpleNamespace(
        base_url="https://api.deepseek.com/anthropic",
        messages=types.SimpleNamespace(create=create),
    )
    result = asyncio.run(recognizer._llm_recognize(MVP, None))
    assert result["intent"] == IntentCategory.SERVICE_INCIDENT
    assert not result.get("failed")
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}


def test_agent_call_uses_reply_budget_and_non_thinking_mode(orchestrator):
    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(
            stop_reason="end_turn",
            usage=types.SimpleNamespace(output_tokens=300),
            content=[{"type": "text", "text": "需要核对发布时间和数据库连接池指标。"}],
        )

    agent = orchestrator._pool[AgentType.APPLICATION][0]
    agent._client = types.SimpleNamespace(
        base_url="https://api.deepseek.com/anthropic",
        messages=types.SimpleNamespace(create=create),
    )
    content = asyncio.run(agent._call_llm(make_request(MVP, IntentCategory.SERVICE_INCIDENT)))
    assert content
    assert captured["max_tokens"] == 4096
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
