"""Shared intent-recognition and diagnosis entry for chat and evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from agents.agent_orchestrator import AgentOrchestrator
from core.diagnosis_pipeline import DiagnosisOutcome, DiagnosisPipeline
from core.intent_recognizer import IntentResult


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
) -> RecognizedDiagnosis:
    intent = await orchestrator.recognize_intent(message, history=history)
    outcome = await pipeline.run(
        message=message, user_id=user_id, conv_id=conv_id,
        memory_context=memory_context, history=history,
        intent_result=intent, environment=environment,
        anchor_time=anchor_time,
    )
    return RecognizedDiagnosis(intent=intent, outcome=outcome)
