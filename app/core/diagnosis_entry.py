"""Shared intent-recognition and diagnosis entry for chat and evaluation."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional

from agents.agent_orchestrator import AgentOrchestrator
from core.diagnosis_pipeline import DiagnosisOutcome, DiagnosisPipeline
from core.intent_recognizer import IntentResult
from core.rootlens_config import project_rootlens_entities


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
) -> RecognizedDiagnosis:
    intent = await orchestrator.recognize_intent(message, history=history)
    intent = replace(intent, entities=project_rootlens_entities(intent.entities))
    outcome = await pipeline.run(
        message=message, user_id=user_id, conv_id=conv_id,
        memory_context=memory_context, history=history,
        intent_result=intent, environment=environment,
        anchor_time=anchor_time,
        build_diagnosis=build_diagnosis,
    )
    return RecognizedDiagnosis(intent=intent, outcome=outcome)
