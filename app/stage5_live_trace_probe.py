"""Run the shared diagnosis core with real services and print safe trace summaries.

Usage (from E:/code/RootLens/app): Get-Content -Raw stage5_live_trace_probe.py |
       docker compose exec -T echomind python -
This does not expose a public trace or failure-injection endpoint.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from uuid import uuid4

from api import main
from core.diagnosis_entry import run_diagnosis


CASES = (
    ("INC-001", "payment-service 从 10:05 开始 5xx 激增，刚发布 v2.3.7，帮我判断原因",
     "demo", "2026-09-01T10:05:00+08:00"),
    ("runbook-db-pool", "如何处理 DBConnectionError 连接池耗尽？请查 Runbook", None, None),
    ("clarify-missing-service", "10:05 开始 5xx 激增，请帮我排查", None, None),
    ("INC-004-partial", "shipping-service 13:05 开始 5xx 升高，帮我排查",
     "demo", "2026-09-01T13:05:00+08:00"),
)


async def probe() -> None:
    os.environ["PROMETHEUS_PORT"] = "0"
    logging.disable(logging.ERROR)
    selected = set(os.getenv("STAGE5_PROBE_CASES", "").split(","))
    async with main.lifespan(main.app):
        for case_id, message, environment, anchor in CASES:
            if "" not in selected and case_id not in selected:
                continue
            diagnosis = await run_diagnosis(
                orchestrator=main._orchestrator,
                pipeline=main._diagnosis_pipeline,
                message=message,
                user_id="stage5-probe",
                conv_id=f"stage5-{uuid4().hex}",
                environment=environment,
                anchor_time=datetime.fromisoformat(anchor) if anchor else None,
            )
            outcome = diagnosis.outcome
            result = outcome.result
            trace = outcome.trace
            bundle = outcome.bundle
            if trace is None:
                raise RuntimeError(f"Trace missing for {case_id}")
            serialized = trace.model_dump_json()
            secret = os.getenv("ANTHROPIC_API_KEY", "")
            forbidden = ("authorization", "password", "api_key", "full_prompt",
                         "hidden_reasoning", "stack_trace", "agent_markdown")
            if (secret and secret in serialized) or any(
                marker in serialized.lower() for marker in forbidden
            ):
                raise RuntimeError(f"Unsafe trace payload for {case_id}")
            payload = {
                "case_id": case_id,
                "intent": diagnosis.intent.intent.value,
                "trace_id": trace.trace_id,
                "trace_schema": trace.schema_version,
                "trace_redaction_ok": True,
                "overall_status": trace.overall_status,
                "degraded": trace.degraded,
                "trace_duration_ms": round(
                    (trace.completed_at - trace.started_at).total_seconds() * 1000, 1),
                "steps": [
                    {"type": step.step_type, "status": step.status,
                     "kind": step.result_kind, "ms": round(step.latency_ms, 1),
                     "error": step.error_code,
                     "timing_source": step.metadata.get("timing_source")}
                    for step in trace.steps
                ],
                "agent_windows": [
                    {"start": step.started_at.isoformat(), "end": step.completed_at.isoformat()}
                    for step in trace.steps if step.step_type == "agent_execution"
                ],
                "tool_status": {name: item.status for name, item in
                                bundle.tool_status.items()} if bundle else {},
                "evidence_ids": [item.evidence_id for item in bundle.evidence] if bundle else [],
                "rag_stages": outcome.knowledge.stages,
                "knowledge_ids": [item.document_id for item in outcome.knowledge.sources],
                "primary_agent": result.primary_agent.value if result.primary_agent else None,
                "supporting_agents": [item.value for item in result.supporting_agents],
                "agent_attempts": [
                    {"role": item.role, "requested": item.requested_agent.value,
                     "executed": item.executed_agent.value, "success": item.success,
                     "degraded": item.degraded, "latency_ms": round(item.latency_ms, 1)}
                    for item in result.agent_executions
                ],
                "clarification": outcome.clarification_required,
                "diagnosis_status": outcome.diagnosis_build_result.status.value,
                "diagnosis_schema": (outcome.diagnosis_build_result.diagnosis.schema_version
                                     if outcome.diagnosis_build_result.diagnosis else None),
            }
            print("STAGE5_PROBE " + json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(probe())
