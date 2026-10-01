"""One shared diagnosis path from recognized intent to a single Agent run."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, Optional

from agents.agent_orchestrator import AgentOrchestrator, AgentType, OrchestratorResult, Request
from core.evidence import EvidenceBundle, QueryContext, build_query_context
from core.diagnosis_assembler import DiagnosisAssembler
from core.incident_diagnosis import DiagnosisBuildResult, DiagnosisBuildStatus
from core.intent_recognizer import IntentCategory, IntentResult
from core.rag_query import build_retrieval_query
from core.routing_signals import RoutingSignals, extract_routing_signals
from mcp.tool_manager import MCPToolManager, ToolResult


DIAGNOSTIC_INTENTS = frozenset({
    IntentCategory.SERVICE_INCIDENT, IntentCategory.LATENCY_ISSUE,
    IntentCategory.DEPLOYMENT_ISSUE, IntentCategory.DATABASE_ISSUE,
    IntentCategory.RESOURCE_ISSUE, IntentCategory.NETWORK_ISSUE,
})
EVIDENCE_TOOLS = ("query_logs", "query_metrics", "query_deployments")


@dataclass
class KnowledgeSource:
    document_id: str
    chunk_id: str
    source_ref: str
    source_type: str = ""


@dataclass
class KnowledgeResult:
    text: str = ""
    used: bool = False
    stages: dict[str, str] = field(default_factory=lambda: {
        "rewrite": "skipped", "retrieval": "skipped", "rerank": "skipped",
    })
    sources: list[KnowledgeSource] = field(default_factory=list)


@dataclass
class DiagnosisOutcome:
    result: OrchestratorResult
    knowledge: KnowledgeResult
    bundle: Optional[EvidenceBundle] = None
    signals: RoutingSignals = field(default_factory=RoutingSignals)
    clarification_required: bool = False
    diagnosis_build_result: DiagnosisBuildResult = field(default_factory=lambda: DiagnosisBuildResult(
        status=DiagnosisBuildStatus.NOT_RUN))


def evidence_context(bundle: EvidenceBundle) -> str:
    lines = ["[现场事实：仅以下带 ID 的记录来自模拟运行数据]"]
    for item in bundle.evidence[:30]:
        details = json.dumps(item.attributes.model_dump(exclude_none=True), ensure_ascii=False)
        lines.append(f"[{item.evidence_id}] {item.observed_at.isoformat()} "
                     f"{item.source_type}: {item.summary}; {details}")
    lines.append("[工具状态] " + ", ".join(
        f"{name}={observation.status}" +
        (f" ({observation.error})" if observation.error else "")
        for name, observation in bundle.tool_status.items()
    ))
    lines.append("现场证据和 Runbook 是不同来源；发布先于故障不等于发布是根因。"
                 "没有证据支持的原因只能写为待验证假设。")
    return "\n".join(lines)


class DiagnosisPipeline:
    def __init__(self, *, orchestrator: AgentOrchestrator, tool_manager: MCPToolManager,
                 knowledge_lookup: Callable[[str], Awaitable[KnowledgeResult]],
                 dataset_id: str, dataset_version: str, timezone: str,
                 assembler: Optional[DiagnosisAssembler] = None):
        self.orchestrator = orchestrator
        self.tools = tool_manager
        self.knowledge_lookup = knowledge_lookup
        self.dataset_id = dataset_id
        self.dataset_version = dataset_version
        self.timezone = timezone
        self.assembler = assembler

    async def run(self, *, message: str, user_id: str, conv_id: str,
                  memory_context: str, history: Optional[list[dict[str, str]]],
                  intent_result: IntentResult, environment: Optional[str] = None,
                  anchor_time: Optional[datetime] = None,
                  build_diagnosis: bool = True) -> DiagnosisOutcome:
        intent = intent_result.intent
        entities = intent_result.entities
        event_markers = ("5xx", "500", "异常", "故障", "超时", "告警", "error", "cpu", "内存")
        evidence_required = intent in DIAGNOSTIC_INTENTS or (
            intent == IntentCategory.ALERT_TRIAGE
            and bool(entities.get("service_name"))
            and bool(anchor_time or entities.get("start_time"))
            and (bool(entities.get("status_code") or entities.get("error_code"))
                 or any(marker in message.lower() for marker in event_markers))
        )
        if intent == IntentCategory.ALERT_TRIAGE and not evidence_required:
            return self._clarify(
                intent, "请补充受影响的服务、告警发生时间和具体现象，再进行现场取证。",
                build_diagnosis=build_diagnosis)
        bundle = None
        signals = RoutingSignals()
        if evidence_required:
            query, clarification = build_query_context(
                entities=entities, environment=environment, anchor_time=anchor_time,
                dataset_id=self.dataset_id, dataset_version=self.dataset_version,
                timezone=self.timezone, message=message,
            )
            if clarification:
                return self._clarify(intent, clarification, build_diagnosis=build_diagnosis)
            assert query is not None
            bundle = await self._acquire(query)
            signals = extract_routing_signals(bundle)

        retrieval = build_retrieval_query(message, evidence=bundle)
        knowledge = (await self.knowledge_lookup(retrieval.query)
                     if evidence_required or intent == IntentCategory.RUNBOOK_QUERY
                     else KnowledgeResult())
        knowledge_context = knowledge.text
        if knowledge.stages.get("retrieval") in {"failed", "degraded"}:
            knowledge_context += "\n[知识库状态] 检索未完整成功，不能把降级说明当作 Runbook。"
        context = "\n\n".join(part for part in (memory_context, knowledge_context) if part)
        request = Request(
            message=message, user_id=user_id, conv_id=conv_id, context=context,
            history=history, entities=entities, intent=intent,
            intent_group=intent_result.intent_group, urgency=intent_result.urgency,
            intent_confidence=intent_result.confidence,
            evidence_context=evidence_context(bundle) if bundle else "",
            evidence_entities=signals.entities,
            routing_signals=signals.floors,
            routing_signal_sources=signals.evidence_ids,
        )
        result = await self.orchestrator.run(request)
        build_result = DiagnosisBuildResult(status=DiagnosisBuildStatus.NOT_RUN)
        if build_diagnosis and self.assembler:
            try:
                if result.clarification_required:
                    build_result = self.assembler.clarify(intent, result.response)
                else:
                    build_result = await self.assembler.build(
                        message=message, intent_result=intent_result, result=result,
                        bundle=bundle, knowledge=knowledge)
            except Exception:
                build_result = DiagnosisBuildResult(
                    status=DiagnosisBuildStatus.ASSEMBLER_FAILED,
                    error_code="unexpected_assembler_error")
        return DiagnosisOutcome(result=result, knowledge=knowledge, bundle=bundle,
                                signals=signals, diagnosis_build_result=build_result,
                                clarification_required=result.clarification_required)

    def _clarify(self, intent: IntentCategory, message: str,
                 *, build_diagnosis: bool = True) -> DiagnosisOutcome:
        build_result = DiagnosisBuildResult(status=DiagnosisBuildStatus.NOT_RUN)
        if build_diagnosis and self.assembler:
            build_result = self.assembler.clarify(intent, message)
        return DiagnosisOutcome(
            result=OrchestratorResult(
                request_id="", response=message, agent_type=AgentType.GENERAL,
                intent=intent, agent_types=[], routing_reason="query_context_clarification",
            ), knowledge=KnowledgeResult(), clarification_required=True,
            diagnosis_build_result=build_result,
        )

    async def _acquire(self, query: QueryContext) -> EvidenceBundle:
        results = await asyncio.gather(*(
            self.tools.call(name, query.tool_params(name, limit=30)) for name in EVIDENCE_TOOLS
        ), return_exceptions=True)
        normalized = {
            name: (value if isinstance(value, ToolResult) else ToolResult(
                success=False, data=None, tool_name=name, error=str(value)))
            for name, value in zip(EVIDENCE_TOOLS, results)
        }
        return EvidenceBundle.from_results(query, normalized)
