import logging
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.db import get_db
from app.providers.registry import estimate_cost_usd

logger = logging.getLogger("vedax.observability")


def now() -> datetime:
    return datetime.now(timezone.utc)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(len(ordered) * pct), len(ordered) - 1)
    return round(ordered[index], 1)


async def summary(workspace_id: str) -> dict:
    db = get_db()
    query = {"workspace_id": workspace_id}
    investigations = []
    cursor = db.investigations.find({**query, "status": "completed"}).sort("created_at", -1).limit(500)
    async for investigation in cursor:
        investigations.append(investigation)

    latencies = [i.get("latency_ms", 0) for i in investigations if i.get("latency_ms")]
    model_runs = [run async for run in db.model_runs.find(query).sort("created_at", -1).limit(2000)]

    total_input = sum(r.get("input_tokens", 0) for r in model_runs)
    total_output = sum(r.get("output_tokens", 0) for r in model_runs)
    total_cost = sum(
        estimate_cost_usd(r.get("provider", ""), r.get("model", ""), r.get("input_tokens", 0), r.get("output_tokens", 0))
        for r in model_runs
    )
    fallbacks = sum(1 for r in model_runs if r.get("fallback_used"))
    failures = sum(1 for r in model_runs if not r.get("success", True))

    provider_usage: dict[str, dict] = {}
    for run in model_runs:
        key = f"{run.get('provider', '?')}/{run.get('model', '?')}"
        entry = provider_usage.setdefault(
            key, {"provider": run.get("provider"), "model": run.get("model"), "calls": 0, "tokens": 0, "avg_latency_ms": 0.0}
        )
        entry["calls"] += 1
        entry["tokens"] += run.get("input_tokens", 0) + run.get("output_tokens", 0)
        entry["avg_latency_ms"] += run.get("latency_ms", 0)

    for entry in provider_usage.values():
        if entry["calls"]:
            entry["avg_latency_ms"] = round(entry["avg_latency_ms"] / entry["calls"], 1)

    tool_cursor = db.tool_runs.find(query).limit(2000)
    tool_usage: dict[str, dict] = {}
    async for run in tool_cursor:
        key = run.get("tool", "unknown")
        entry = tool_usage.setdefault(key, {"tool": key, "calls": 0, "successes": 0})
        entry["calls"] += 1
        if run.get("success"):
            entry["successes"] += 1

    return {
        "total_investigations": len(investigations),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "p50_latency_ms": percentile(latencies, 0.5),
        "p95_latency_ms": percentile(latencies, 0.95),
        "total_tokens": total_input + total_output,
        "estimated_cost_usd": round(total_cost, 4),
        "fallback_rate": round(fallbacks / len(model_runs), 3) if model_runs else 0.0,
        "error_rate": round(failures / len(model_runs), 3) if model_runs else 0.0,
        "provider_usage": sorted(provider_usage.values(), key=lambda e: -e["calls"]),
        "tool_usage": list(tool_usage.values()),
    }


async def recent_traces(workspace_id: str, limit: int = 50) -> list[dict]:
    db = get_db()
    query = {"workspace_id": workspace_id}
    cursor = db.investigations.find(query).sort("created_at", -1).limit(limit)
    traces = []
    async for investigation in cursor:
        traces.append(
            {
                "id": investigation["_id"],
                "question": investigation.get("question", ""),
                "status": investigation.get("status"),
                "capabilities": investigation.get("capabilities", []),
                "latency_ms": investigation.get("latency_ms", 0),
                "confidence": investigation.get("confidence"),
                "model_run_count": len(investigation.get("model_runs", [])),
                "tool_run_count": len(investigation.get("tool_runs", [])),
                "created_at": investigation.get("created_at"),
            }
        )
    return traces
