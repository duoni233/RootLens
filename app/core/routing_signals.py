"""Deterministic, provenance-preserving hints from scoped operational evidence."""
from dataclasses import dataclass, field

from core.evidence import (
    DeploymentAttributes, EvidenceBundle, LogAttributes, MetricAttributes,
)


@dataclass
class RoutingSignals:
    floors: dict[str, float] = field(default_factory=dict)
    evidence_ids: dict[str, list[str]] = field(default_factory=dict)
    entities: dict[str, list[str]] = field(default_factory=dict)

    def add(self, domain: str, floor: float, evidence_id: str) -> None:
        self.floors[domain] = max(self.floors.get(domain, 0.0), floor)
        ids = self.evidence_ids.setdefault(domain, [])
        if evidence_id not in ids:
            ids.append(evidence_id)

    def add_entity(self, name: str, value: str) -> None:
        values = self.entities.setdefault(name, [])
        if value not in values:
            values.append(value)


def extract_routing_signals(bundle: EvidenceBundle) -> RoutingSignals:
    signals = RoutingSignals()
    source_tools = {"log": "query_logs", "metric": "query_metrics",
                    "deployment": "query_deployments"}
    for item in bundle.evidence:
        if item.evidence_category != "operational":
            continue
        observation = bundle.tool_status.get(source_tools[item.source_type])
        if observation is None or observation.status != "ok":
            continue
        if isinstance(item.attributes, LogAttributes):
            code = (item.attributes.error_code or "").lower()
            message = item.attributes.message.lower()
            if code.startswith("db") or "pool exhausted" in message or "连接池耗尽" in message:
                signals.add("database", 0.55, item.evidence_id)
            if code.startswith("http5") or "5xx" in message or "application failure" in message:
                signals.add("application", 0.75, item.evidence_id)
            if any(term in message for term in ("cpu", "memory", "node resource", "内存")):
                signals.add("infrastructure", 0.65, item.evidence_id)
            if item.attributes.error_code:
                signals.add_entity("error_code", item.attributes.error_code)
        elif isinstance(item.attributes, MetricAttributes):
            name = item.attributes.metric_name.lower()
            if name in {"http_5xx_rate", "http_500_rate"} and (
                item.attributes.unit == "percent" and item.attributes.value >= 5
            ):
                signals.add("application", 0.75, item.evidence_id)
            if name in {"cpu_usage", "memory_usage", "node_cpu_usage", "node_memory_usage"} and (
                item.attributes.unit == "percent" and item.attributes.value >= 80
            ):
                signals.add("infrastructure", 0.65, item.evidence_id)
        elif isinstance(item.attributes, DeploymentAttributes):
            if item.attributes.status == "succeeded":
                signals.add("application", 0.55, item.evidence_id)
                signals.add_entity("version", item.attributes.version)
    return signals
