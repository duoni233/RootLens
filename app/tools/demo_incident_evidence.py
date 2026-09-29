"""Run with: python -m tools.demo_incident_evidence (no API requests)."""
import asyncio
import json

from core.evidence import EvidenceBundle, QueryContext
from mcp.incident_tools import IncidentTools
from mcp.tool_manager import MCPToolManager


async def main():
    tools = IncidentTools()
    ctx = QueryContext.build(
        service_name="payment-service", environment="demo",
        anchor_time="2026-09-01T10:05:00+08:00", timezone="Asia/Shanghai",
        dataset_id=tools.manifest.dataset_id, dataset_version=tools.manifest.dataset_version,
    )
    manager = MCPToolManager(api_key="offline-demo-not-a-real-key")
    try:
        tools.register(manager)
        names = ("query_logs", "query_metrics", "query_deployments")
        results = await asyncio.gather(*(manager.call(name, ctx.tool_params(name)) for name in names))
        bundle = EvidenceBundle.from_results(ctx, dict(zip(names, results)))
        print(json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, indent=2))
    finally:
        await manager._client.close()


if __name__ == "__main__":
    asyncio.run(main())
