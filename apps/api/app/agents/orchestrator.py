import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from app.agents import events
from app.agents.graph import get_graph
from app.core.db import get_db
from app.core.logging import new_trace_id
from app.observability import langfuse
from app.providers.base import RunContext

logger = logging.getLogger("vedax.orchestrator")


def now() -> datetime:
    return datetime.now(timezone.utc)


async def get_or_create_conversation(
    workspace_id: str, conversation_id: str | None, first_message: str
) -> dict:
    db = get_db()
    if conversation_id:
        existing = await db.conversations.find_one(
            {"_id": conversation_id, "workspace_id": workspace_id}
        )
        if existing:
            return existing
    conversation = {
        "_id": uuid.uuid4().hex,
        "workspace_id": workspace_id,
        "title": first_message[:80],
        "created_at": now(),
        "updated_at": now(),
    }
    await db.conversations.insert_one(conversation)
    return conversation


async def load_history(conversation_id: str, limit: int = 10) -> list[dict]:
    db = get_db()
    cursor = (
        db.messages.find({"conversation_id": conversation_id})
        .sort("created_at", -1)
        .limit(limit)
    )
    messages = [m async for m in cursor]
    return [
        {"role": m["role"], "content": m.get("content", "")} for m in reversed(messages)
    ]


async def run_investigation(
    *,
    workspace_id: str,
    user_id: str,
    question: str,
    conversation_id: str | None,
    attachment_ids: list[str] | None,
    audio_media_id: str | None,
    retrieval_mode: str = "hybrid_rerank",
) -> AsyncIterator[dict[str, Any]]:
    db = get_db()
    conversation = await get_or_create_conversation(
        workspace_id, conversation_id, question or "Voice question"
    )
    history = await load_history(conversation["_id"])
    investigation_id = uuid.uuid4().hex
    trace_id = new_trace_id()
    model_runs: list[dict] = []
    tool_runs: list[dict] = []

    def on_run(run: dict[str, Any]) -> None:
        if "tool" in run:
            tool_runs.append(run)
        else:
            model_runs.append(run)

    run_ctx = RunContext(
        investigation_id=investigation_id,
        conversation_id=conversation["_id"],
        workspace_id=workspace_id,
        trace_id=trace_id,
        on_run=on_run,
    )

    investigation = {
        "_id": investigation_id,
        "workspace_id": workspace_id,
        "user_id": user_id,
        "conversation_id": conversation["_id"],
        "trace_id": trace_id,
        "question": question,
        "answer": "",
        "capabilities": [],
        "citations": [],
        "charts": [],
        "evidence": [],
        "confidence": None,
        "model_runs": [],
        "tool_runs": [],
        "status": "running",
        "latency_ms": 0.0,
        "created_at": now(),
    }
    await db.investigations.insert_one(investigation)

    await db.messages.insert_one(
        {
            "_id": uuid.uuid4().hex,
            "conversation_id": conversation["_id"],
            "workspace_id": workspace_id,
            "role": "user",
            "content": question,
            "attachment_ids": attachment_ids or [],
            "investigation_id": investigation_id,
            "created_at": now(),
        }
    )

    state: dict[str, Any] = {
        "workspace_id": workspace_id,
        "user_id": user_id,
        "conversation_id": conversation["_id"],
        "investigation_id": investigation_id,
        "question": question,
        "original_question": question,
        "history": history,
        "attachment_ids": attachment_ids or [],
        "audio_media_id": audio_media_id,
        "retrieval_mode": retrieval_mode,
        "retry_count": 0,
        "errors": [],
    }

    emitter_token = None
    ctx_token = None
    started = time.perf_counter()
    lf_span = None
    try:
        queue: asyncio.Queue = asyncio.Queue()

        def collector(event: dict) -> None:
            queue.put_nowait(event)
            if event.get("type") == "node" and lf_span is not None:
                langfuse.record_event(
                    lf_span,
                    name=f"node:{event.get('node', '?')}",
                    event_type="node_execution",
                    metadata={"detail": event.get("detail", "")},
                )

        emitter_token = events.set_emitter(collector)
        ctx_token = events.set_run_ctx(run_ctx)
        graph = get_graph()
        merged: dict[str, Any] = {}

        from app.observability.langfuse import _get_client

        lf_client = _get_client()
        if lf_client is not None:
            try:
                trace_obj = lf_client.trace(
                    name=f"investigation:{question[:60]}",
                    metadata={
                        "investigation_id": investigation_id,
                        "workspace_id": workspace_id,
                        "user_id": user_id,
                    },
                    user_id=user_id,
                    tags=["investigation", retrieval_mode],
                )
                lf_span = trace_obj
                run_ctx.langfuse_trace = lf_span
            except Exception:
                lf_span = None

        async def pump() -> None:
            nonlocal pump_error
            try:
                async for update in graph.astream(state, stream_mode="updates"):
                    for node_name in update:
                        merged.update(update[node_name] or {})
            except Exception as exc:
                logger.error("graph pump failed: %s", exc)
                pump_error = exc
            finally:
                queue.put_nowait(None)

        pump_error: Exception | None = None
        pump_task = asyncio.create_task(pump())
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
        await pump_task
        if pump_error is not None:
            raise pump_error

        final_state = merged
        answer = final_state.get("answer", "")
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        citations = final_state.get("citations", [])
        charts = final_state.get("charts", [])
        evidence = final_state.get("evidence", [])
        capabilities = final_state.get("capabilities", [])
        confidence = final_state.get("confidence")

        if lf_span is not None:
            try:
                lf_span.update(
                    metadata={
                        "answer_length": len(answer),
                        "citations_count": len(citations),
                        "charts_count": len(charts),
                        "capabilities": capabilities,
                        "confidence": confidence,
                    },
                )
                langfuse.record_event(
                    lf_span,
                    name="investigation_complete",
                    event_type="completion",
                    metadata={
                        "latency_ms": latency_ms,
                        "answer_preview": answer[:200],
                    },
                )
            except Exception:
                pass

        await db.investigations.update_one(
            {"_id": investigation_id},
            {
                "$set": {
                    "answer": answer,
                    "citations": citations,
                    "charts": charts,
                    "evidence": evidence,
                    "capabilities": capabilities,
                    "confidence": confidence,
                    "model_runs": model_runs,
                    "tool_runs": tool_runs,
                    "status": "completed",
                    "latency_ms": latency_ms,
                }
            },
        )
        await db.messages.insert_one(
            {
                "_id": uuid.uuid4().hex,
                "conversation_id": conversation["_id"],
                "workspace_id": workspace_id,
                "role": "assistant",
                "content": answer,
                "investigation_id": investigation_id,
                "citations": citations,
                "charts": charts,
                "confidence": confidence,
                "created_at": now(),
            }
        )
        await db.conversations.update_one(
            {"_id": conversation["_id"]}, {"$set": {"updated_at": now()}}
        )
        if model_runs:
            for run in model_runs:
                run.update(
                    {
                        "investigation_id": investigation_id,
                        "workspace_id": workspace_id,
                        "trace_id": trace_id,
                        "created_at": now(),
                    }
                )
            await db.model_runs.insert_many(model_runs)
        if tool_runs:
            for run in tool_runs:
                run.update(
                    {
                        "investigation_id": investigation_id,
                        "workspace_id": workspace_id,
                        "trace_id": trace_id,
                        "created_at": now(),
                    }
                )
            await db.tool_runs.insert_many(tool_runs)

        yield {
            "type": "done",
            "investigation": {
                "id": investigation_id,
                "conversation_id": conversation["_id"],
                "question": question,
                "answer": answer,
                "capabilities": capabilities,
                "citations": citations,
                "charts": charts,
                "confidence": confidence,
                "latency_ms": latency_ms,
                "model_runs": [
                    {
                        "provider": r.get("provider"),
                        "model": r.get("model"),
                        "task": r.get("task"),
                        "latency_ms": r.get("latency_ms", 0),
                        "input_tokens": r.get("input_tokens", 0),
                        "output_tokens": r.get("output_tokens", 0),
                    }
                    for r in model_runs
                ],
                "tool_calls": len(tool_runs),
            },
        }
    except Exception as exc:
        logger.error("investigation failed: %s", exc, exc_info=True)
        await db.investigations.update_one(
            {"_id": investigation_id},
            {"$set": {"status": "failed", "error": str(exc)[:500]}},
        )
        yield {"type": "error", "message": f"Investigation failed: {str(exc)[:300]}"}
    finally:
        if emitter_token is not None:
            events.reset_emitter(emitter_token)
        if ctx_token is not None:
            events.reset_run_ctx(ctx_token)
        langfuse.flush()
