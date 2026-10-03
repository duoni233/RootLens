"""Request-scoped, non-sensitive observations of one diagnosis execution."""
from __future__ import annotations

import time
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


StepStatus = Literal["success", "failed", "degraded", "skipped"]
OverallStatus = Literal["success", "failed", "degraded"]

_METADATA_KEYS = frozenset({
    "intent", "intent_latency_ms", "source_names", "decision", "cached",
    "record_count", "result_count",
    "primary_agent", "supporting_agents", "domain_scores", "requested_agent",
    "executed_agent", "agent_latency_ms", "role", "escalated", "fallback", "build_status",
    "input_tokens", "output_tokens", "llm_called", "timing_source", "skip_reason",
})


class TraceStep(BaseModel):
    step_id: str
    step_type: str
    component: str
    status: StepStatus
    started_at: datetime
    completed_at: datetime
    latency_ms: float = Field(ge=0)
    result_kind: Literal["items", "empty"] | None = None
    error_code: str | None = None
    degraded: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    knowledge_ids: list[str] = Field(default_factory=list)


class DiagnosisTrace(BaseModel):
    schema_version: Literal["1"] = "1"
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    request_id: str | None = None
    eval_run_id: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    overall_status: OverallStatus | None = None
    degraded: bool = False
    steps: list[TraceStep] = Field(default_factory=list)


@dataclass(frozen=True)
class StepHandle:
    step_type: str
    component: str
    started_at: datetime
    started_ns: int


class TraceRecorder:
    def __init__(self, *, eval_run_id: str | None = None):
        self.trace = DiagnosisTrace(eval_run_id=eval_run_id)

    def begin(self, step_type: str, component: str) -> StepHandle:
        return StepHandle(step_type, component, datetime.now(timezone.utc), time.monotonic_ns())

    def finish(self, handle: StepHandle, status: StepStatus, *,
               result_kind: Literal["items", "empty"] | None = None,
               error_code: str | None = None, degraded: bool = False,
               metadata: dict[str, Any] | None = None,
               evidence_ids: list[str] | None = None,
               knowledge_ids: list[str] | None = None,
               completed_at: datetime | None = None,
               elapsed_ms: float | None = None) -> None:
        completed_at = completed_at or datetime.now(timezone.utc)
        elapsed_ms = (max(0, (time.monotonic_ns() - handle.started_ns) / 1_000_000)
                      if elapsed_ms is None else max(0, elapsed_ms))
        self.trace.steps.append(TraceStep(
            step_id=str(len(self.trace.steps) + 1), step_type=handle.step_type,
            component=handle.component, status=status, started_at=handle.started_at,
            completed_at=completed_at, latency_ms=elapsed_ms,
            result_kind=result_kind, error_code=error_code,
            degraded=degraded or status == "degraded",
            metadata={key: value for key, value in (metadata or {}).items()
                      if key in _METADATA_KEYS},
            evidence_ids=evidence_ids or [], knowledge_ids=knowledge_ids or [],
        ))

    def skipped(self, step_type: str, component: str, reason: str) -> None:
        handle = self.begin(step_type, component)
        self.finish(handle, "skipped", metadata={"skip_reason": reason})

    def has_step(self, step_type: str) -> bool:
        return any(step.step_type == step_type for step in self.trace.steps)

    def complete(self, *, request_id: str | None, usable: bool) -> DiagnosisTrace:
        self.trace.request_id = request_id or None
        self.trace.completed_at = datetime.now(timezone.utc)
        impaired = any(step.status in {"failed", "degraded"} or step.degraded
                       for step in self.trace.steps)
        self.trace.degraded = impaired
        self.trace.overall_status = ("degraded" if impaired else "success") if usable else "failed"
        return self.trace


_CURRENT: ContextVar[TraceRecorder | None] = ContextVar("rootlens_diagnosis_trace", default=None)


def current_trace() -> TraceRecorder | None:
    return _CURRENT.get()


def activate_trace(recorder: TraceRecorder) -> Token:
    return _CURRENT.set(recorder)


def reset_trace(token: Token) -> None:
    _CURRENT.reset(token)


def begin_step(step_type: str, component: str) -> StepHandle | None:
    try:
        recorder = current_trace()
        return recorder.begin(step_type, component) if recorder else None
    except Exception:
        return None


def finish_step(handle: StepHandle | None, status: StepStatus, **kwargs: Any) -> None:
    if handle is None:
        return
    try:
        recorder = current_trace()
        if recorder:
            recorder.finish(handle, status, **kwargs)
    except Exception:
        pass


def skip_step(step_type: str, component: str, reason: str) -> None:
    try:
        recorder = current_trace()
        if recorder and not recorder.has_step(step_type):
            recorder.skipped(step_type, component, reason)
    except Exception:
        pass


def observed_step(step_type: str, component: str, status: StepStatus,
                  **kwargs: Any) -> None:
    """Map an existing result when the implementation owns no timed child stage."""
    try:
        recorder = current_trace()
        if recorder and not recorder.has_step(step_type):
            handle = recorder.begin(step_type, component)
            metadata = dict(kwargs.pop("metadata", {}))
            metadata["timing_source"] = "not_measured"
            recorder.finish(handle, status, metadata=metadata, **kwargs)
    except Exception:
        pass
