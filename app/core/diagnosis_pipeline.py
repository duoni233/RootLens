"""One shared diagnosis path from recognized intent to a single Agent run."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from agents.agent_orchestrator import AgentOrchestrator, AgentType, OrchestratorResult, Request
from core.evidence import EvidenceBundle, QueryContext, build_query_context
from core.diagnosis_assembler import DiagnosisAssembler
from core.diagnosis_trace import (
    DiagnosisTrace, begin_step, finish_step, observed_step, skip_step,
)
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
    trace: Optional[DiagnosisTrace] = None


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
        gate_step = begin_step("evidence_gate", "DiagnosisPipeline")
        finish_step(gate_step, "success", metadata={
            "decision": "acquire" if evidence_required else "skip",
        })
        if intent == IntentCategory.ALERT_TRIAGE and not evidence_required:
            return self._clarify(
                intent, "请补充受影响的服务、告警发生时间和具体现象，再进行现场取证。",
                build_diagnosis=build_diagnosis)
        bundle = None
        signals = RoutingSignals()
        if evidence_required:
            query_step = begin_step("query_context", "QueryContext")
            try:
                query, clarification = build_query_context(
                    entities=entities, environment=environment, anchor_time=anchor_time,
                    dataset_id=self.dataset_id, dataset_version=self.dataset_version,
                    timezone=self.timezone, message=message,
                )
            except Exception:
                finish_step(query_step, "failed", error_code="query_context_error")
                raise
            finish_step(query_step, "success", metadata={
                "decision": "clarify" if clarification else "query",
            })
            if clarification:
                return self._clarify(intent, clarification, build_diagnosis=build_diagnosis)
            assert query is not None
            bundle = await self._acquire(query)
            signals = extract_routing_signals(bundle)
        else:
            skip_step("query_context", "QueryContext", "evidence_not_required")
            for name in EVIDENCE_TOOLS:
                skip_step(name, "IncidentTools", "evidence_not_required")

        retrieval = build_retrieval_query(message, evidence=bundle)
        if evidence_required or intent == IntentCategory.RUNBOOK_QUERY:
            knowledge = await self.knowledge_lookup(retrieval.query)
            for stage in ("rewrite", "retrieval", "rerank"):
                stage_type = f"rag_{stage}"
                state = knowledge.stages.get(stage, "skipped")
                if state == "skipped":
                    skip_step(stage_type, "KnowledgeRetrieval", "stage_not_executed")
                else:
                    observed_step(
                        stage_type, "KnowledgeRetrieval",
                        "degraded" if state in {"failed", "degraded"} else "success",
                        error_code=f"{stage}_failed" if state == "failed" else None,
                        metadata={"result_count": len(knowledge.sources)},
                        knowledge_ids=[source.chunk_id for source in knowledge.sources]
                        if stage != "rewrite" else [],
                    )
        else:
            knowledge = KnowledgeResult()
            for stage in ("rewrite", "retrieval", "rerank"):
                skip_step(f"rag_{stage}", "KnowledgeRetrieval", "knowledge_not_required")
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
        if result.clarification_required:
            skip_step("routing", "AgentOrchestrator", "clarification")
            skip_step("agent_execution", "AgentOrchestrator", "clarification")
        build_result = DiagnosisBuildResult(status=DiagnosisBuildStatus.NOT_RUN)
        if build_diagnosis and self.assembler:
            assembly_step = begin_step("diagnosis_assembly", "DiagnosisAssembler")
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
            finish_step(
                assembly_step, "success" if build_result.status == DiagnosisBuildStatus.SUCCESS
                else "failed", error_code=build_result.error_code,
                metadata={
                    "build_status": build_result.status.value,
                    "input_tokens": build_result.input_tokens,
                    "output_tokens": build_result.output_tokens,
                    "llm_called": not result.clarification_required,
                },
            )
        else:
            skip_step("diagnosis_assembly", "DiagnosisAssembler", "assembly_not_requested")
        return DiagnosisOutcome(result=result, knowledge=knowledge, bundle=bundle,
                                signals=signals, diagnosis_build_result=build_result,
                                clarification_required=result.clarification_required)

    def _clarify(self, intent: IntentCategory, message: str,
                 *, build_diagnosis: bool = True) -> DiagnosisOutcome:
        for name in EVIDENCE_TOOLS:
            skip_step(name, "IncidentTools", "clarification")
        for stage in ("rewrite", "retrieval", "rerank"):
            skip_step(f"rag_{stage}", "KnowledgeRetrieval", "clarification")
        skip_step("query_context", "QueryContext", "clarification_before_query")
        skip_step("routing", "AgentOrchestrator", "clarification")
        skip_step("agent_execution", "AgentOrchestrator", "clarification")
        build_result = DiagnosisBuildResult(status=DiagnosisBuildStatus.NOT_RUN)
        if build_diagnosis and self.assembler:
            assembly_step = begin_step("diagnosis_assembly", "DiagnosisAssembler")
            build_result = self.assembler.clarify(intent, message)
            finish_step(assembly_step,
                        "success" if build_result.status == DiagnosisBuildStatus.SUCCESS else "failed",
                        error_code=build_result.error_code,
                        metadata={"build_status": build_result.status.value,
                                  "llm_called": False})
        else:
            skip_step("diagnosis_assembly", "DiagnosisAssembler", "assembly_not_requested")
        return DiagnosisOutcome(
            result=OrchestratorResult(
                request_id="", response=message, agent_type=AgentType.GENERAL,
                intent=intent, agent_types=[], routing_reason="query_context_clarification",
            ), knowledge=KnowledgeResult(), clarification_required=True,
            diagnosis_build_result=build_result,
        )

    async def _acquire(self, query: QueryContext) -> EvidenceBundle:
        params_by_name = {name: query.tool_params(name, limit=30) for name in EVIDENCE_TOOLS}

        async def call_one(name: str):
            handle = begin_step(name, "IncidentTools")
            try:
                value = await self.tools.call(name, params_by_name[name])
            except Exception as ex:
                value = ex
            completed_at = datetime.now(timezone.utc)
            elapsed_ms = ((time.monotonic_ns() - handle.started_ns) / 1_000_000
                          if handle else None)
            return value, handle, completed_at, elapsed_ms

        raw = await asyncio.gather(*(call_one(name) for name in EVIDENCE_TOOLS),
                                   return_exceptions=True)
        observed = [item if isinstance(item, tuple) else
                    (item, None, datetime.now(timezone.utc), None) for item in raw]
        results = [item[0] for item in observed]
        normalized = {
            name: (value if isinstance(value, ToolResult) else ToolResult(
                success=False, data=None, tool_name=name, error=str(value)))
            for name, value in zip(EVIDENCE_TOOLS, results)
        }
        bundle = EvidenceBundle.from_results(query, normalized)
        source_types = {"query_logs": "log", "query_metrics": "metric",
                        "query_deployments": "deployment"}
        for name, (value, handle, completed_at, elapsed_ms) in zip(EVIDENCE_TOOLS, observed):
            state = bundle.tool_status[name]
            status = {"ok": "success", "empty": "success",
                      "failed": "failed", "degraded": "degraded"}[state.status]
            error_code = None
            if state.status in {"failed", "degraded"}:
                error = (state.error or "").lower()
                error_code = ("tool_timeout" if "超时" in error or "timeout" in error
                              else "circuit_open" if "熔断" in error
                              else "tool_unavailable")
            finish_step(
                handle, status, result_kind=("items" if state.status == "ok" else "empty"
                                            if state.status == "empty" else None),
                error_code=error_code,
                metadata={"cached": getattr(value, "cached", False),
                          "record_count": sum(item.source_type == source_types[name]
                                              for item in bundle.evidence),
                          "fallback": state.status == "degraded"},
                evidence_ids=[item.evidence_id for item in bundle.evidence
                              if item.source_type == source_types[name]],
                completed_at=completed_at, elapsed_ms=elapsed_ms,
            )
        return bundle
