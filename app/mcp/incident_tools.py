"""Read-only, explicitly simulated incident tools registered with the existing manager."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pydantic import Field

from core.evidence import (
    Contract, DeploymentQuery, Evidence, LogQuery, MetricQuery, Name,
    OperationalRecord, within_window,
)
from mcp.tool_manager import Tool

LEGACY_RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "datasets" / "runtime"
DEFAULT_RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "datasets" / "snapshots" / "v2" / "runtime"
SOURCE_FILES = {"log": "logs.json", "metric": "metrics.json",
                "deployment": "deployments.json"}


class RuntimeManifest(Contract):
    dataset_id: Name
    dataset_version: Name
    simulated: bool
    timezone: Name
    incident_ids: list[Name] = Field(min_length=1)


class IncidentTools:
    def __init__(self, runtime_root=DEFAULT_RUNTIME_ROOT,
                 clock: Callable = lambda: datetime.now(timezone.utc)):
        self.root = Path(runtime_root).resolve(strict=True)
        if self.root.name != "runtime":
            raise ValueError("runtime loader requires a dedicated runtime directory")
        self.clock = clock
        self.manifest = RuntimeManifest.model_validate(self._read_json("manifest.json"))
        if not self.manifest.simulated:
            raise ValueError("this loader only supports explicitly simulated data")
        if len(set(self.manifest.incident_ids)) != len(self.manifest.incident_ids):
            raise ValueError("duplicate incident IDs")
        for incident in self.manifest.incident_ids:
            if not re.fullmatch(r"INC-[0-9]+", incident):
                raise ValueError("invalid incident directory ID")

    def _allowed_path(self, relative: str) -> Path:
        allowed = {"manifest.json"}
        if hasattr(self, "manifest"):
            allowed.update(f"{incident}/{filename}"
                           for incident in self.manifest.incident_ids
                           for filename in SOURCE_FILES.values())
        if relative not in allowed:
            raise ValueError("not a runtime source file")
        path = (self.root / relative).resolve(strict=True)
        if self.root not in path.parents:
            raise ValueError("source escapes runtime directory")
        return path

    def _read_json(self, relative: str):
        with self._allowed_path(relative).open(encoding="utf-8") as stream:
            return json.load(stream)

    def resolve_raw_ref(self, raw_ref: str) -> OperationalRecord:
        relative, separator, record_id = raw_ref.partition("#")
        if not separator:
            raise ValueError("raw_ref needs a source record ID")
        records = self._records(relative)
        for record in records:
            if record.record_id == record_id:
                return record
        raise ValueError("record ID not found")

    def _records(self, relative: str) -> list[OperationalRecord]:
        raw = self._read_json(relative)
        if not isinstance(raw, list):
            raise ValueError("source file must contain a list")
        records = [OperationalRecord.model_validate(item) for item in raw]
        ids = [item.record_id for item in records]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate source record IDs")
        return records

    def _query(self, source: str, query) -> list[dict]:
        if query.dataset_version != self.manifest.dataset_version:
            raise ValueError("dataset_version does not match the loaded snapshot")
        retrieved_at = self.clock()
        found = []
        for incident in self.manifest.incident_ids:
            relative = f"{incident}/{SOURCE_FILES[source]}"
            for record in self._records(relative):
                if record.source_type != source:
                    raise ValueError("record source_type does not match its file")
                if (record.service_name != query.service_name
                        or record.environment != query.environment
                        or not within_window(record, query)):
                    continue
                attrs = record.attributes
                if source == "log" and (
                    (query.severity and attrs.severity != query.severity)
                    or (query.error_code and attrs.error_code != query.error_code)
                ):
                    continue
                if source == "metric" and query.metric_names is not None:
                    if attrs.metric_name not in query.metric_names:
                        continue
                if source == "deployment" and query.version and attrs.version != query.version:
                    continue
                evidence = Evidence(
                    **record.model_dump(),
                    evidence_id=f"{self.manifest.dataset_id}:{self.manifest.dataset_version}:"
                                f"{incident}:{source}:{record.record_id}",
                    dataset_id=self.manifest.dataset_id,
                    dataset_version=self.manifest.dataset_version,
                    raw_ref=f"{relative}#{record.record_id}", retrieved_at=retrieved_at,
                )
                found.append(evidence)
        found.sort(key=lambda item: (item.observed_at, item.evidence_id))
        return [item.model_dump(mode="json") for item in found[:query.limit]]

    async def query_logs(self, params: dict, context=None) -> list[dict]:
        return await asyncio.to_thread(self._query, "log", LogQuery.model_validate(params))

    async def query_metrics(self, params: dict, context=None) -> list[dict]:
        return await asyncio.to_thread(self._query, "metric", MetricQuery.model_validate(params))

    async def query_deployments(self, params: dict, context=None) -> list[dict]:
        return await asyncio.to_thread(self._query, "deployment",
                                       DeploymentQuery.model_validate(params))

    def register(self, manager, *, cache_ttl=30.0, timeout_s=5.0):
        for name, model in (("query_logs", LogQuery), ("query_metrics", MetricQuery),
                            ("query_deployments", DeploymentQuery)):
            manager.register(Tool(
                name=name, description=f"Read simulated incident {name.removeprefix('query_')}",
                handler=getattr(self, name), schema=model.model_json_schema(),
                cache_ttl=cache_ttl, timeout_s=timeout_s, fallback=None,
            ))
