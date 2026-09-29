"""Operational evidence contracts; no routing or LLM decisions live here."""
from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Annotated, Literal, Optional, Union
from zoneinfo import ZoneInfo

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, StringConstraints,
    model_validator,
)

Name = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceCategory(str, Enum):
    OPERATIONAL = "operational"
    KNOWLEDGE = "knowledge"


class TimeWindow(Contract):
    start_time: AwareDatetime
    end_time: AwareDatetime

    @model_validator(mode="after")
    def ordered(self):
        if self.end_time < self.start_time:
            raise ValueError("end_time must be at or after start_time")
        return self


class WindowPolicy(Contract):
    lookback_minutes: Annotated[StrictInt, Field(ge=0, le=1440)] = 5
    lookahead_minutes: Annotated[StrictInt, Field(ge=0, le=1440)] = 15
    deployment_lookback_minutes: Annotated[StrictInt, Field(ge=0, le=1440)] = 60


class OperationalQuery(TimeWindow):
    service_name: Name
    environment: Name
    dataset_version: Name
    limit: Annotated[StrictInt, Field(ge=1, le=1000)] = 100


class LogQuery(OperationalQuery):
    severity: Optional[Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]] = None
    error_code: Optional[Name] = None


class MetricQuery(OperationalQuery):
    metric_names: Optional[list[Name]] = None


class DeploymentQuery(OperationalQuery):
    version: Optional[Name] = None


class QueryContext(Contract):
    service_name: Name
    environment: Name
    anchor_time: AwareDatetime
    timezone: Name
    dataset_id: Name
    dataset_version: Name
    logs_window: TimeWindow
    metrics_window: TimeWindow
    deployments_window: TimeWindow
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_timezone(self):
        ZoneInfo(self.timezone)
        return self

    @classmethod
    def build(cls, *, service_name, environment, anchor_time, timezone,
              dataset_id, dataset_version, policy=None, assumptions=None):
        # Parse a complete aware timestamp before calculating any query window.
        anchor = TimeWindow(start_time=anchor_time, end_time=anchor_time).start_time
        anchor = anchor.astimezone(ZoneInfo(timezone))
        policy = policy or WindowPolicy()
        nearby = TimeWindow(
            start_time=anchor - timedelta(minutes=policy.lookback_minutes),
            end_time=anchor + timedelta(minutes=policy.lookahead_minutes),
        )
        return cls(
            service_name=service_name, environment=environment, anchor_time=anchor,
            timezone=timezone, dataset_id=dataset_id, dataset_version=dataset_version,
            logs_window=nearby, metrics_window=nearby,
            deployments_window=TimeWindow(
                start_time=anchor - timedelta(minutes=policy.deployment_lookback_minutes),
                end_time=anchor,
            ),
            assumptions=assumptions or [],
        )

    def tool_params(self, tool_name: str, limit: int = 100) -> dict:
        window = {
            "query_logs": self.logs_window,
            "query_metrics": self.metrics_window,
            "query_deployments": self.deployments_window,
        }[tool_name]
        return OperationalQuery(
            service_name=self.service_name, environment=self.environment,
            dataset_version=self.dataset_version, limit=limit,
            **window.model_dump(),
        ).model_dump(mode="json")


class LogAttributes(Contract):
    severity: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    error_code: Optional[Name] = None
    message: Name


class MetricAttributes(Contract):
    metric_name: Name
    value: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    unit: Name
    aggregation: Name


class DeploymentAttributes(Contract):
    version: Name
    status: Literal["succeeded", "failed", "rolled_back"]


class OperationalRecord(Contract):
    record_id: Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9_-]+$")]
    source_type: Literal["log", "metric", "deployment"]
    service_name: Name
    environment: Name
    observed_at: AwareDatetime
    time_range: Optional[TimeWindow] = None
    summary: Name
    attributes: Union[LogAttributes, MetricAttributes, DeploymentAttributes]

    @model_validator(mode="after")
    def matching_attributes(self):
        expected = {"log": LogAttributes, "metric": MetricAttributes,
                    "deployment": DeploymentAttributes}[self.source_type]
        if not isinstance(self.attributes, expected):
            raise ValueError("attributes do not match source_type")
        if self.source_type == "metric":
            if self.time_range is None or not (
                self.time_range.start_time <= self.observed_at <= self.time_range.end_time
            ):
                raise ValueError("metric requires an interval containing observed_at")
        elif self.time_range is not None:
            raise ValueError("point events must not have a time_range")
        return self


class Evidence(OperationalRecord):
    evidence_category: Literal["operational"] = "operational"
    evidence_id: Name
    dataset_id: Name
    dataset_version: Name
    raw_ref: Name
    retrieved_at: AwareDatetime


class ToolObservation(Contract):
    status: Literal["ok", "empty", "failed", "degraded"]
    cached: bool = False
    error: Optional[str] = None


class EvidenceBundle(Contract):
    query_context: QueryContext
    evidence: list[Evidence] = Field(default_factory=list)
    tool_status: dict[str, ToolObservation] = Field(default_factory=dict)

    @classmethod
    def from_results(cls, query_context: QueryContext, results: dict):
        evidence, status, seen = [], {}, set()
        expected_sources = {"query_logs": "log", "query_metrics": "metric",
                            "query_deployments": "deployment"}
        for name, source in expected_sources.items():
            result = results.get(name)
            if result is None or not result.success:
                status[name] = ToolObservation(
                    status="failed", error=getattr(result, "error", None) or "missing result")
                continue
            if result.error:
                status[name] = ToolObservation(status="degraded", error=result.error,
                                               cached=result.cached)
                continue
            try:
                if not isinstance(result.data, list):
                    raise ValueError("tool data must be a list")
                items = [Evidence.model_validate(item) for item in result.data]
                params = OperationalQuery.model_validate(query_context.tool_params(name))
                for item in items:
                    if (item.source_type != source or item.dataset_id != query_context.dataset_id
                            or item.dataset_version != params.dataset_version
                            or item.service_name != params.service_name
                            or item.environment != params.environment
                            or not within_window(item, params)):
                        raise ValueError("evidence is outside query scope")
                for item in items:
                    if item.evidence_id not in seen:
                        seen.add(item.evidence_id)
                        evidence.append(item)
                status[name] = ToolObservation(status="ok" if items else "empty",
                                               cached=result.cached)
            except (ValueError, TypeError) as ex:
                status[name] = ToolObservation(status="failed", error=str(ex))
        return cls(query_context=query_context, evidence=evidence, tool_status=status)


def within_window(record: OperationalRecord, window: TimeWindow) -> bool:
    if record.time_range is not None:
        return (window.start_time <= record.time_range.start_time
                and record.time_range.end_time <= window.end_time)
    return window.start_time <= record.observed_at <= window.end_time
