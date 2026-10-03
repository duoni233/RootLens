"""Deterministic component failures applied only inside a pytest context."""
from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pytest import MonkeyPatch

from agents.agent_orchestrator import AgentResponse, AgentType


_ALLOWED = {
    "query_logs": frozenset({"timeout", "empty"}),
    "query_metrics": frozenset({"exception"}),
    "rag_rewrite": frozenset({"exception"}),
    "rag_retrieval": frozenset({"exception"}),
    "supporting_agent:database": frozenset({"exception"}),
    "primary_agent:application": frozenset({"failed_response"}),
    "diagnosis_assembler": frozenset({"malformed_json", "api_exception", "invalid_ref"}),
}


@dataclass(frozen=True)
class FailurePlan:
    target: str
    failure: str

    def __post_init__(self):
        if self.failure not in _ALLOWED.get(self.target, ()):
            raise ValueError(f"unsupported test failure: {self.target}/{self.failure}")


class TestFailureController:
    """Replace one test boundary and restore it on exit; never writes Trace."""

    __test__ = False

    def __init__(self, pipeline, plan: FailurePlan):
        self.pipeline = pipeline
        self.plan = plan
        self._patch = MonkeyPatch()

    def __enter__(self):
        try:
            self._apply()
        except Exception:
            self._patch.undo()
            raise
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._patch.undo()
        return False

    def _apply(self):
        target, failure = self.plan.target, self.plan.failure
        manager = self.pipeline.tools
        if target in {"query_logs", "query_metrics", "rag_retrieval"}:
            name = "knowledge_search" if target == "rag_retrieval" else target
            tool = manager._tools.get(name)
            if tool is None:
                raise ValueError(f"test tool not registered: {name}")
            self._patch.setattr(manager, "_cache", {})
            self._patch.setattr(tool, "cache_ttl", 0.0)
            self._patch.setattr(tool, "stats", copy.deepcopy(tool.stats))
            self._patch.setattr(tool, "breaker", copy.deepcopy(tool.breaker))
            if failure == "timeout":
                async def slow(params, context):
                    await asyncio.sleep(0.05)
                    return []
                self._patch.setattr(tool, "timeout_s", 0.005)
                self._patch.setattr(tool, "handler", slow)
            elif failure == "empty":
                async def empty(params, context):
                    return []
                self._patch.setattr(tool, "handler", empty)
            else:
                async def raise_error(params, context):
                    raise RuntimeError("controlled tool exception")
                self._patch.setattr(tool, "handler", raise_error)
            return

        if target == "rag_rewrite":
            self._patch.setattr(
                manager._client.messages, "create",
                AsyncMock(side_effect=RuntimeError("controlled rewrite exception")),
            )
            return

        if target.startswith(("primary_agent:", "supporting_agent:")):
            agent_type = (AgentType.APPLICATION if target.endswith("application")
                          else AgentType.DATABASE)
            agents = self.pipeline.orchestrator._pool.get(agent_type, [])
            if not agents:
                raise ValueError(f"test agent not registered: {agent_type.value}")
            if failure == "failed_response":
                async def fail_response(request):
                    return AgentResponse(agent_type, "controlled agent failure", False)
                self._patch.setattr(agents[0], "handle", fail_response)
            else:
                async def raise_error(request):
                    raise RuntimeError("controlled supporting agent exception")
                self._patch.setattr(agents[0], "handle", raise_error)
            return

        if target == "diagnosis_assembler":
            assembler = self.pipeline.assembler
            if assembler is None:
                raise ValueError("diagnosis assembler not configured")
            if failure == "api_exception":
                replacement = AsyncMock(side_effect=RuntimeError("controlled model exception"))
            else:
                if failure == "malformed_json":
                    payload = "not-json"
                else:
                    payload = json.dumps({
                        "summary": "unsupported finding",
                        "confirmed_findings": [{"statement": "unsupported",
                                                "evidence_ids": ["UNKNOWN-EVIDENCE-ID"]}],
                        "hypotheses": [], "recommended_actions": [], "evidence_gaps": [],
                    })
                replacement = AsyncMock(return_value=SimpleNamespace(
                    stop_reason="end_turn", content=[{"type": "text", "text": payload}],
                ))
            self._patch.setattr(assembler.client.messages, "create", replacement)
            return

        raise ValueError(f"unsupported test target: {target}")
