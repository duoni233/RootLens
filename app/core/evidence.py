"""Operational evidence contracts; no routing or LLM decisions live here."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from enum import Enum
import re
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


DEMO_DATE = date(2026, 9, 1)


def build_query_context(*, entities: dict, environment: Optional[str] = None,
                        anchor_time: Optional[datetime] = None,
                        dataset_id: str = "rootlens-demo", dataset_version: str = "v1",
                        timezone: str = "Asia/Shanghai",
                        message: str = "") -> tuple[Optional[QueryContext], Optional[str]]:
    """Resolve only explicit conditions, except the visible date assumption in demo."""
    services = list(dict.fromkeys(entities.get("service_name") or []))
    if not services:
        missing_time = not anchor_time and not entities.get("start_time")
        detail = "，以及故障发生时间" if missing_time else ""
        return None, ("请提供受影响的服务名（如 payment-service）" + detail +
                      "，并说明看到的错误或具体现象。当前只能查询已登记的模拟服务，不能直接访问真实后台。")
    if len(services) != 1:
        return None, "识别到多个服务名，请确认本次需要调查哪一个服务。"
    env_in_text = re.findall(r"(?<![\w-])(demo|prod|staging)(?![\w-])", message, re.I)
    if len({value.lower() for value in env_in_text}) > 1 or (
        environment and env_in_text and environment.lower() != env_in_text[0].lower()
    ):
        return None, "请求中的环境条件不一致，请确认是 demo、staging 还是 prod。"
    env = (environment or (env_in_text[0] if env_in_text else "demo")).lower()
    assumptions = [] if environment or env_in_text else ["未指定环境，使用显式模拟环境 demo"]
    times = list(dict.fromkeys(entities.get("start_time") or []))
    dates = list(dict.fromkeys(entities.get("date") or []))
    try:
        event_times = [time(*(int(part) for part in value.split(":"))) for value in times]
        parsed_dates = []
        for value in dates:
            match = re.fullmatch(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", value)
            if match is None:
                raise ValueError("unsupported date")
            parsed_dates.append(date(*(int(part) for part in match.groups())))
    except ValueError:
        return None, "故障发生时间格式无效，请使用完整日期和 HH:MM。"
    if anchor_time is not None:
        if anchor_time.tzinfo is None or anchor_time.utcoffset() is None:
            return None, "请提供带时区的完整发生时间。"
        anchor = anchor_time
        local = anchor.astimezone(ZoneInfo(timezone))
        if (event_times and local.time().replace(tzinfo=None).replace(second=0, microsecond=0)
                not in event_times or parsed_dates and local.date() not in parsed_dates):
            return None, "请求时间与消息中的故障时间不一致，请确认本次发生时间。"
    else:
        if len(event_times) > 1 or len(parsed_dates) > 1:
            return None, "出现多个故障时间，请确认本次需要查询的时间。"
        event_time = event_times[0] if event_times else None
        day = parsed_dates[0] if parsed_dates else None
        if event_time is None:
            return None, "请提供明确的故障发生时间，例如 2026-09-01 10:05。"
        if day is None and env == "demo":
            day = DEMO_DATE
            assumptions.append("未提供日期，demo 数据使用 2026-09-01 Asia/Shanghai")
        if day is None:
            return None, "非 demo 环境需要提供完整日期和时间，不会猜测日期。"
        anchor = datetime.combine(day, event_time, tzinfo=ZoneInfo(timezone))
    return QueryContext.build(
        service_name=services[0], environment=env, anchor_time=anchor,
        timezone=timezone, dataset_id=dataset_id, dataset_version=dataset_version,
        assumptions=assumptions,
    ), None
