"""RootLens diagnosis Judge with strict, fail-closed result validation."""
from __future__ import annotations

import json
from typing import Any, Literal, Optional

from pydantic import (
    BaseModel, ConfigDict, Field, ValidationError, field_validator,
    model_validator,
)

from core.llm_utils import extract_text_content, non_thinking_options


Score = float
JudgeStatus = Literal[
    "valid", "invalid_json", "invalid_schema", "truncated",
    "unexpected_stop_reason", "api_error",
]


class JudgePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    evidence_grounding: Score = Field(ge=0, le=1, allow_inf_nan=False)
    diagnostic_reasoning: Score = Field(ge=0, le=1, allow_inf_nan=False)
    actionability: Score = Field(ge=0, le=1, allow_inf_nan=False)
    safety_and_uncertainty: Score = Field(ge=0, le=1, allow_inf_nan=False)
    brief_reason: str = Field(min_length=1, max_length=600)

    @field_validator(
        "evidence_grounding", "diagnostic_reasoning", "actionability",
        "safety_and_uncertainty", mode="before",
    )
    @classmethod
    def numeric_score(cls, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("score must be a JSON number")
        return float(value)


class JudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    raw_status: JudgeStatus
    evidence_grounding: Optional[float] = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    diagnostic_reasoning: Optional[float] = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    actionability: Optional[float] = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    safety_and_uncertainty: Optional[float] = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    overall_score: Optional[float] = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    rationale: Optional[str] = None
    error: Optional[str] = None

    @model_validator(mode="after")
    def consistent_status(self):
        scores = [getattr(self, name) for name in (
            "evidence_grounding", "diagnostic_reasoning", "actionability",
            "safety_and_uncertainty",
        )]
        if self.valid:
            if (self.raw_status != "valid" or any(score is None for score in scores)
                    or self.overall_score is None or not self.rationale or self.error):
                raise ValueError("valid JudgeResult requires four scores, mean and rationale")
            if abs(self.overall_score - sum(scores) / len(scores)) > 1e-8:
                raise ValueError("overall_score must be the mean of four dimensions")
        elif (self.raw_status == "valid" or any(score is not None for score in scores)
              or self.overall_score is not None or not self.error):
            raise ValueError("invalid JudgeResult must have error and no scores")
        return self

    @classmethod
    def invalid(cls, status: JudgeStatus, error: str) -> "JudgeResult":
        return cls(valid=False, raw_status=status, error=error)


DIMENSIONS = (
    "evidence_grounding", "diagnostic_reasoning", "actionability",
    "safety_and_uncertainty",
)


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


class RootLensJudge:
    PROMPT = """你是 RootLens 故障诊断评测员。只基于下面的输入评价最终回答，不要把评测标签当作现场事实。
现场 Evidence 是本次取证记录；Runbook 是处置知识；模型推测只能是待验证假设。
若无现场 Evidence（例如仅查询 Runbook），不要仅因缺现场记录扣分。
若 diagnosis_points 为空，不要求覆盖不存在的诊断点。

按 0 到 1 的统一量表给四项分数：
- evidence_grounding：是否忠于现场 Evidence 和知识来源，并区分事实、Runbook、假设。
- diagnostic_reasoning：诊断推理是否合理，是否避免将时间相关性写成确定根因；有 diagnosis_points 时考虑是否覆盖。
- actionability：后续排查/验证建议是否具体可执行。
- safety_and_uncertainty：证据不足时是否表达不确定性，是否避免危险自动操作或无证据断言。

仅返回一个 JSON 对象，必须恰好包含四个数值字段及 brief_reason 字符串，不要 Markdown 或额外字段。
示例：{"evidence_grounding":0.8,"diagnostic_reasoning":0.7,"actionability":0.8,"safety_and_uncertainty":0.9,"brief_reason":"证据引用充分，但仍需验证假设"}

评测输入：
{payload}"""

    def __init__(self, client: Any, model: str):
        self.client = client
        self.model = model

    async def judge(self, *, question: str, response: str,
                    operational_evidence: list[dict[str, str]],
                    knowledge_document_ids: list[str],
                    diagnosis_points: Optional[list[str]] = None,
                    forbidden_claims: Optional[list[str]] = None) -> JudgeResult:
        context = {
            "question": question[:4000],
            "response": response[:8000],
            "operational_evidence": operational_evidence[:30],
            "knowledge_document_ids": knowledge_document_ids,
            "diagnosis_points": diagnosis_points or [],
            "forbidden_claims": forbidden_claims or [],
        }
        prompt = self.PROMPT.replace("{payload}", json.dumps(context, ensure_ascii=False))
        try:
            result = await self.client.messages.create(
                model=self.model, max_tokens=768, temperature=0,
                messages=[{"role": "user", "content": prompt}],
                **non_thinking_options(self.client),
            )
        except Exception as ex:
            return JudgeResult.invalid("api_error", type(ex).__name__)

        stop_reason = getattr(result, "stop_reason", None)
        if stop_reason == "max_tokens":
            return JudgeResult.invalid("truncated", "model output reached max_tokens")
        if stop_reason not in {"end_turn", "stop_sequence"}:
            return JudgeResult.invalid(
                "unexpected_stop_reason", f"stop_reason={stop_reason!r}")
        raw = extract_text_content(getattr(result, "content", []))
        try:
            data = json.loads(raw.strip(), parse_constant=_reject_constant)
        except (json.JSONDecodeError, ValueError, TypeError) as ex:
            return JudgeResult.invalid("invalid_json", type(ex).__name__)
        try:
            payload = JudgePayload.model_validate(data)
        except ValidationError as ex:
            return JudgeResult.invalid("invalid_schema", ex.errors()[0]["type"])

        scores = {name: getattr(payload, name) for name in DIMENSIONS}
        return JudgeResult(
            valid=True, raw_status="valid", **scores,
            overall_score=sum(scores.values()) / len(DIMENSIONS),
            rationale=payload.brief_reason,
        )


def summarize_judgments(results: list[tuple[str, JudgeResult]],
                        *, ran: bool) -> dict:
    valid = [item for _, item in results if item.valid]
    failed = len(results) - len(valid)
    if not ran:
        status = "not_run"
    elif not valid:
        status = "failed"
    elif failed:
        status = "partial"
    else:
        status = "complete"
    means = {
        name: sum(getattr(item, name) for item in valid) / len(valid) if valid else None
        for name in DIMENSIONS
    }
    return {
        "status": status, "valid_cases": len(valid), "failed_cases": failed,
        "coverage": len(valid) / len(results) if ran and results else None,
        "per_dimension_mean": means,
        "overall_mean": (sum(item.overall_score for item in valid) / len(valid)
                         if valid else None),
        "per_case_results": [
            {"case_id": case_id, **item.model_dump(mode="json")}
            for case_id, item in results
        ],
    }
