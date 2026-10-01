"""Evaluate the same diagnosis core used by /chat, without Judge or Redis I/O."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from agents.agent_orchestrator import AgentOrchestrator
from core.diagnosis_entry import run_diagnosis
from core.diagnosis_pipeline import DiagnosisPipeline
from evaluation.rootlens_cases import EvaluationCase, EvaluationObservation
from evaluation.rootlens_metrics import Metric, score_cases


@dataclass
class RootLensEvalReport:
    observations: list[EvaluationObservation]
    metrics: dict[str, Metric]
    judge_status: str = "not_run"

    def to_dict(self) -> dict:
        return {
            "mode": "rootlens_deterministic",
            "total": len(self.observations),
            "judge_status": self.judge_status,
            "metrics": {
                name: {
                    "numerator": metric.numerator,
                    "denominator": metric.denominator,
                    "value": metric.value,
                }
                for name, metric in self.metrics.items()
            },
            "observations": [item.model_dump(mode="json") for item in self.observations],
        }


class RootLensEvaluator:
    def __init__(self, *, orchestrator: AgentOrchestrator, pipeline: DiagnosisPipeline):
        self.orchestrator = orchestrator
        self.pipeline = pipeline

    async def run(self, cases: list[EvaluationCase]) -> RootLensEvalReport:
        run_id = uuid4().hex
        observations = []
        for index, case in enumerate(cases):
            history: list[dict[str, str]] = []
            case_observation = None
            identity = f"eval:{run_id}:{index}"
            for runtime_input in case.runtime_inputs():
                diagnosis = await run_diagnosis(
                    orchestrator=self.orchestrator, pipeline=self.pipeline,
                    message=runtime_input.message,
                    user_id=identity, conv_id=identity,
                    memory_context="", history=history[-5:] or None,
                    environment=runtime_input.environment,
                    anchor_time=runtime_input.anchor_time,
                )
                outcome = diagnosis.outcome
                result = outcome.result
                bundle = outcome.bundle
                case_observation = EvaluationObservation(
                    case_id=case.case_id,
                    intent=diagnosis.intent.intent.value,
                    primary_agent=(result.primary_agent.value if result.primary_agent
                                   else None if outcome.clarification_required
                                   else result.agent_type.value),
                    supporting_agents=[agent.value for agent in result.supporting_agents],
                    evidence_ids=[item.evidence_id for item in bundle.evidence] if bundle else [],
                    evidence_types=sorted({item.source_type for item in bundle.evidence})
                                   if bundle else [],
                    tool_status={name: state.status for name, state in bundle.tool_status.items()}
                                if bundle else {},
                    knowledge_document_ids=list(dict.fromkeys(
                        source.document_id for source in outcome.knowledge.sources)),
                    runbook_ids=list(dict.fromkeys(
                        source.document_id for source in outcome.knowledge.sources
                        if source.source_type == "runbook")),
                    clarification_required=outcome.clarification_required,
                    response=result.response,
                    rag_stage_status=dict(outcome.knowledge.stages),
                )
                history.extend((
                    {"role": "user", "content": runtime_input.message},
                    {"role": "assistant", "content": result.response},
                ))
            assert case_observation is not None
            observations.append(case_observation)

        # Labels are touched only after every runtime call has completed.
        return RootLensEvalReport(observations=observations,
                                  metrics=score_cases(cases, observations))
