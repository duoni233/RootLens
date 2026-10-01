"""Private evaluation labels and the runtime-only input projection."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


DEFAULT_CASES = Path(__file__).resolve().parents[1] / "datasets" / "evaluation" / "stage3-v1.json"
ToolStatus = Literal["ok", "empty", "failed", "degraded"]


class ExpectedResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Optional[str] = None
    primary_agent: Optional[str] = None
    supporting_agents: Optional[list[str]] = None
    evidence_ids: Optional[list[str]] = None
    evidence_types: Optional[list[str]] = None
    tool_status: Optional[dict[str, ToolStatus]] = None
    runbook_ids: Optional[list[str]] = None
    diagnosis_points: Optional[list[str]] = None
    forbidden_claims: Optional[list[str]] = None
    clarification_required: Optional[bool] = None


class RuntimeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str
    environment: Optional[str] = None
    anchor_time: Optional[AwareDatetime] = None


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    message: Optional[str] = None
    messages: Optional[list[str]] = None
    environment: Optional[str] = None
    anchor_time: Optional[AwareDatetime] = None
    expected: ExpectedResult

    @model_validator(mode="after")
    def one_input_form(self):
        if (self.message is None) == (self.messages is None):
            raise ValueError("provide exactly one of message or messages")
        if self.message is not None and not self.message.strip():
            raise ValueError("message cannot be empty")
        if self.messages is not None and (not self.messages or any(not m.strip() for m in self.messages)):
            raise ValueError("messages must contain nonempty turns")
        return self

    def runtime_inputs(self) -> list[RuntimeInput]:
        """Never expose expected labels to the diagnosis runtime."""
        return [RuntimeInput(message=message, environment=self.environment,
                             anchor_time=self.anchor_time)
                for message in (self.messages if self.messages is not None else [self.message])]


class EvaluationObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    intent: Optional[str] = None
    primary_agent: Optional[str] = None
    supporting_agents: Optional[list[str]] = None
    evidence_ids: Optional[list[str]] = None
    evidence_types: Optional[list[str]] = None
    tool_status: Optional[dict[str, ToolStatus]] = None
    runbook_ids: Optional[list[str]] = None
    knowledge_document_ids: Optional[list[str]] = None
    clarification_required: Optional[bool] = None
    response: Optional[str] = None
    rag_stage_status: dict[str, str] = Field(default_factory=dict)


def load_rootlens_cases(path: Optional[Path] = None) -> list[EvaluationCase]:
    source = Path(path) if path is not None else Path(
        os.getenv("ROOTLENS_EVAL_CASES_PATH", str(DEFAULT_CASES)))
    with source.open(encoding="utf-8") as stream:
        cases = [EvaluationCase.model_validate(item) for item in json.load(stream)]
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate evaluation case IDs")
    return cases
