"""Shared intent-recognition and diagnosis entry for chat and evaluation."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional

from agents.agent_orchestrator import AgentOrchestrator
from core.diagnosis_pipeline import DiagnosisOutcome, DiagnosisPipeline
from core.intent_recognizer import IntentResult
from core.rootlens_config import project_rootlens_entities
from core.diagnosis_trace import (
    TraceRecorder, activate_trace, begin_step, finish_step, reset_trace,
)


@dataclass
class RecognizedDiagnosis:
    intent: IntentResult
    outcome: DiagnosisOutcome


async def run_diagnosis(
    *,
    orchestrator: AgentOrchestrator,
    pipeline: DiagnosisPipeline,
    message: str,
    user_id: str,
    conv_id: str,
    memory_context: str = "",
    history: Optional[list[dict[str, str]]] = None,
    environment: Optional[str] = None,
    anchor_time: Optional[datetime] = None,
    build_diagnosis: bool = True,
    eval_run_id: str | None = None,
) -> RecognizedDiagnosis:
    try:
        recorder = TraceRecorder(eval_run_id=eval_run_id)
        token = activate_trace(recorder)
    except Exception:
        recorder, token = None, None
    try:
        intent_step = begin_step("intent_recognition", "IntentRecognizer")
        try:
            intent = await orchestrator.recognize_intent(message, history=history)
        except Exception:
            finish_step(intent_step, "failed", error_code="intent_recognition_failed")
            raise
        finish_step(intent_step, "success", metadata={
            "intent": intent.intent.value, "intent_latency_ms": intent.latency_ms,
            "source_names": sorted(intent.source_scores),
        })
        intent = replace(intent, entities=project_rootlens_entities(intent.entities))
        outcome = await pipeline.run(
            message=message, user_id=user_id, conv_id=conv_id,
            memory_context=memory_context, history=history,
            intent_result=intent, environment=environment,
            anchor_time=anchor_time,
            build_diagnosis=build_diagnosis,
        )
        if recorder:
            try:
                result = outcome.result
                records = result.agent_executions
                usable = bool(result.response) and (
                    outcome.clarification_required or not records or any(r.success for r in records)
                )
                outcome.trace = recorder.complete(request_id=result.request_id, usable=usable)
            except Exception:
                pass
        return RecognizedDiagnosis(intent=intent, outcome=outcome)
    finally:
        if token is not None:
            try:
                reset_trace(token)
            except Exception:
                pass
