"""Evaluate the same diagnosis core used by /chat, without Redis I/O."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from agents.agent_orchestrator import AgentOrchestrator
from core.diagnosis_entry import run_diagnosis
from core.diagnosis_pipeline import DiagnosisPipeline
from evaluation.rootlens_baseline import (
    BaselineStore, EVALUATION_SCHEMA_VERSION, JUDGE_SCHEMA_VERSION,
    SUITE_NAME, SUITE_VERSION, suite_fingerprint,
)
from evaluation.rootlens_cases import EvaluationCase, EvaluationObservation
from evaluation.rootlens_judge import RootLensJudge, summarize_judgments
from evaluation.rootlens_metrics import Metric, score_cases


@dataclass
class RootLensEvalReport:
    observations: list[EvaluationObservation]
    metrics: dict[str, Metric]
    suite: dict
    judge: dict
    baseline: dict
    regression: dict

    @property
    def judge_status(self) -> str:
        return self.judge["status"]

    def to_dict(self) -> dict:
        return {
            "mode": ("rootlens_judged" if self.judge["status"] != "not_run"
                     else "rootlens_deterministic"),
            "total": len(self.observations),
            "judge_status": self.judge["status"],
            "suite": self.suite,
            "metrics": {
                name: {
                    "numerator": metric.numerator,
                    "denominator": metric.denominator,
                    "value": metric.value,
                }
                for name, metric in self.metrics.items()
            },
            "judge": self.judge,
            "baseline": self.baseline,
            "regression": self.regression,
            "observations": [item.model_dump(mode="json") for item in self.observations],
        }


class RootLensEvaluator:
    def __init__(self, *, orchestrator: AgentOrchestrator, pipeline: DiagnosisPipeline,
                 judge: RootLensJudge | None = None,
                 baseline_store: BaselineStore | None = None,
                 model: str = "unspecified", provider: str = "unspecified"):
        self.orchestrator = orchestrator
        self.pipeline = pipeline
        self.judge = judge
        self.baseline_store = baseline_store or BaselineStore()
        self.model = model
        self.provider = provider

    async def run(self, cases: list[EvaluationCase],
                  *, include_judge: bool = False) -> RootLensEvalReport:
        if include_judge and self.judge is None:
            raise ValueError("RootLens Judge is not configured")
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
                    operational_evidence=[
                        {"evidence_id": item.evidence_id, "source_type": item.source_type,
                         "summary": item.summary}
                        for item in bundle.evidence
                    ] if bundle else [],
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
        metrics = score_cases(cases, observations)
        judgments = []
        if include_judge:
            for case, observed in zip(cases, observations):
                result = await self.judge.judge(
                    question=case.runtime_inputs()[-1].message,
                    response=observed.response or "",
                    operational_evidence=observed.operational_evidence,
                    knowledge_document_ids=observed.knowledge_document_ids or [],
                    diagnosis_points=case.expected.diagnosis_points,
                    forbidden_claims=case.expected.forbidden_claims,
                )
                judgments.append((case.case_id, result))
        judge_summary = summarize_judgments(judgments, ran=include_judge)
        suite = {
            "suite_name": SUITE_NAME, "suite_version": SUITE_VERSION,
            "dataset_id": self.pipeline.dataset_id,
            "dataset_version": self.pipeline.dataset_version,
            "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
            "judge_schema_version": JUDGE_SCHEMA_VERSION,
            "model": self.model, "provider": self.provider,
            "case_ids": sorted(case.case_id for case in cases),
            "suite_fingerprint": suite_fingerprint(cases),
        }
        draft = RootLensEvalReport(
            observations=observations, metrics=metrics, suite=suite,
            judge=judge_summary, baseline={}, regression={},
        )
        baseline, regression = self.baseline_store.compare(draft.to_dict())
        draft.baseline = baseline
        draft.regression = regression
        return draft
