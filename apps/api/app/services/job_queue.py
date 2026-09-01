import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from app.core.db import get_db

logger = logging.getLogger("vedax.job_queue")

JobStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
JobKind = Literal["parse", "ocr", "embed", "index", "transcribe", "analyze_image", "analyze_data"]


def now() -> datetime:
    return datetime.now(timezone.utc)


async def enqueue(
    kind: JobKind,
    payload: dict[str, Any],
    workspace_id: str,
    priority: int = 0,
    timeout_seconds: int = 300,
) -> str:
    db = get_db()
    job_id = uuid.uuid4().hex
    job = {
        "_id": job_id,
        "kind": kind,
        "status": "pending",
        "workspace_id": workspace_id,
        "payload": payload,
        "priority": priority,
        "timeout_seconds": timeout_seconds,
        "result": None,
        "error": None,
        "attempts": 0,
        "max_attempts": 3,
        "created_at": now(),
        "started_at": None,
        "completed_at": None,
    }
    await db.jobs.insert_one(job)
    return job_id


async def claim_job() -> dict | None:
    db = get_db()
    now_ts = now()
    job = await db.jobs.find_one_and_update(
        {"status": "pending", "attempts": {"$lt": 3}},
        {
            "$set": {"status": "running", "started_at": now_ts},
            "$inc": {"attempts": 1},
        },
        sort=[("priority", -1), ("created_at", 1)],
        return_document=True,
    )
    return job


async def complete_job(job_id: str, result: dict[str, Any]) -> None:
    db = get_db()
    await db.jobs.update_one(
        {"_id": job_id},
        {"$set": {"status": "completed", "result": result, "completed_at": now()}},
    )


async def fail_job(job_id: str, error: str) -> None:
    db = get_db()
    await db.jobs.update_one(
        {"_id": job_id},
        {"$set": {"status": "failed", "error": error[:1000], "completed_at": now()}},
    )


async def cancel_job(job_id: str) -> bool:
    db = get_db()
    result = await db.jobs.update_one(
        {"_id": job_id, "status": "pending"},
        {"$set": {"status": "cancelled", "completed_at": now()}},
    )
    return result.modified_count > 0


async def get_job(job_id: str, workspace_id: str) -> dict | None:
    db = get_db()
    return await db.jobs.find_one({"_id": job_id, "workspace_id": workspace_id})


async def list_jobs(
    workspace_id: str, status: JobStatus | None = None, limit: int = 50
) -> list[dict]:
    db = get_db()
    query: dict[str, Any] = {"workspace_id": workspace_id}
    if status:
        query["status"] = status
    cursor = db.jobs.find(query).sort("created_at", -1).limit(limit)
    return [job async for job in cursor]


async def cleanup_stale_jobs(timeout_seconds: int = 600) -> int:
    db = get_db()
    cutoff = datetime.fromtimestamp(time.time() - timeout_seconds, tz=timezone.utc)
    result = await db.jobs.update_many(
        {"status": "running", "started_at": {"$lt": cutoff}},
        {"$set": {"status": "failed", "error": "job timed out", "completed_at": now()}},
    )
    return result.modified_count
