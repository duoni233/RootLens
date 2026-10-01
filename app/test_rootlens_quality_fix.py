"""Deterministic Stage 3-4.1B taxonomy, entity, and version boundaries."""
from pathlib import Path

import pytest

from agents.agent_orchestrator import AgentOrchestrator, AgentType, Request
from core.intent_recognizer import IntentCategory, IntentRecognizer
from core.rootlens_config import ROOTLENS_ENTITY_FIELDS, project_rootlens_entities
from evaluation.rootlens_baseline import suite_fingerprint
from evaluation.rootlens_cases import load_rootlens_cases


@pytest.mark.parametrize("message,expected", [
    ("payment-service 10:05 开始 5xx 激增", IntentCategory.SERVICE_INCIDENT),
    ("payment-service 发布 v2.3.7 后开始 5xx 激增", IntentCategory.DEPLOYMENT_ISSUE),
    ("刚发布完 payment-service 就出现大量 5xx", IntentCategory.DEPLOYMENT_ISSUE),
    ("payment-service 5xx 激增，不确定是否与发布有关", IntentCategory.SERVICE_INCIDENT),
    ("帮我看看 payment-service 最近一次发布有没有问题", IntentCategory.DEPLOYMENT_ISSUE),
])
def test_release_focus_pattern_boundaries(message, expected):
    recognizer = IntentRecognizer(api_key="offline", base_url="https://example.invalid")
    assert recognizer._pattern_recognize(message)["intent"] == expected


def test_rootlens_entity_projection_keeps_only_meaningful_incident_fields():
    assert ROOTLENS_ENTITY_FIELDS == (
        "date", "service_name", "start_time", "version", "status_code", "error_code",
    )
    raw = {
        "order_id": ["AB1234"], "product": ["subscription"], "amount": ["¥99"],
        "date": None, "service_name": [" payment-service ", ""],
        "start_time": ["  "], "version": ["v2.3.7"],
        "status_code": [], "error_code": ["DBConnectionError"],
    }
    assert project_rootlens_entities(raw) == {
        "service_name": ["payment-service"], "version": ["v2.3.7"],
        "error_code": ["DBConnectionError"],
    }


def test_legacy_entities_and_router_paths_remain_available():
    recognizer = IntentRecognizer(api_key="offline", base_url="https://example.invalid")
    raw = recognizer._extract_entities("订单号 AB1234，金额 ¥99")
    assert raw["order_id"] == ["AB1234"]
    assert raw["amount"] == ["¥99"]
    assert project_rootlens_entities(raw) == {}

    orchestrator = AgentOrchestrator(api_key="offline", base_url="https://example.invalid")
    common = dict(message="账单查询", user_id="legacy", conv_id="legacy",
                  intent=IntentCategory.OTHER)
    old_scores = orchestrator._domain_scores(Request(**common, entities=raw))
    empty_scores = orchestrator._domain_scores(Request(**common))
    assert old_scores[AgentType.DATABASE] > empty_scores[AgentType.DATABASE]
    assert old_scores[AgentType.GENERAL] > empty_scores[AgentType.GENERAL]


def test_stage3_v1_is_preserved_and_v2_changes_only_adjudicated_label():
    dataset_dir = Path(__file__).parent / "datasets" / "evaluation"
    old = load_rootlens_cases(dataset_dir / "stage3-v1.json")
    current = load_rootlens_cases()
    assert len(old) == len(current) == 6
    assert [case.case_id for case in old] == [case.case_id for case in current]
    assert old[0].expected.intent == "service_incident"
    assert current[0].expected.intent == "deployment_issue"
    assert [item.model_dump(mode="json") for item in old[1:]] == [
        item.model_dump(mode="json") for item in current[1:]]
    assert suite_fingerprint(old) != suite_fingerprint(current)
