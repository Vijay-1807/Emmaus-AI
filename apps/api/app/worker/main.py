import asyncio
import logging
import signal
import sys

from app.services.job_queue import claim_job, complete_job, fail_job, cleanup_stale_jobs

logger = logging.getLogger("vedax.worker")

STOP = asyncio.Event()

JOB_HANDLERS = {}


def register_handler(kind: str):
    def decorator(func):
        JOB_HANDLERS[kind] = func
        return func
    return decorator


@register_handler("parse")
async def handle_parse(payload: dict) -> dict:
    from app.ingestion.parser import parse_document
    result = parse_document(
        payload["filename"], payload.get("content_type", ""),
        bytes.fromhex(payload["data_hex"]),
    )
    return {"pages": len(result.pages), "source_type": result.source_type}


@register_handler("ocr")
async def handle_ocr(payload: dict) -> dict:
    from app.vision.analyzer import ocr_image
    import base64
    image_data = base64.b64decode(payload["image_b64"])
    result = await ocr_image(image_data, payload.get("mime", "image/png"))
    return {"text_length": len(result.get("text", ""))}


@register_handler("embed")
async def handle_embed(payload: dict) -> dict:
    from app.rag.embeddings import get_embedding_service
    svc = get_embedding_service()
    vectors = await svc.embed(payload["texts"])
    return {"count": len(vectors), "dimensions": len(vectors[0]) if vectors else 0}


@register_handler("transcribe")
async def handle_transcribe(payload: dict) -> dict:
    from app.audio.transcriber import transcribe_audio
    import base64
    audio_data = base64.b64decode(payload["data_hex"])
    result = await transcribe_audio(audio_data, payload["filename"], payload.get("content_type"))
    return {"text": result["text"][:500]}


@register_handler("analyze_image")
async def handle_analyze_image(payload: dict) -> dict:
    from app.vision.analyzer import analyze_image
    import base64
    image_data = base64.b64decode(payload["data_hex"])
    result = await analyze_image(image_data, payload.get("mime", "image/png"))
    return {"description": result.get("description", "")[:300]}


@register_handler("index")
async def handle_index(payload: dict) -> dict:
    from app.ingestion.indexer import index_chunks
    from app.rag.embeddings import get_embedding_service
    chunks = payload.get("chunks", [])
    svc = get_embedding_service()
    num = await index_chunks(
        payload["workspace_id"], payload["document_id"], payload["filename"],
        payload["source_type"], chunks, svc, svc.settings.embedding_model,
    )
    return {"indexed_chunks": num}


async def process_job(job: dict) -> None:
    kind = job["kind"]
    handler = JOB_HANDLERS.get(kind)
    if not handler:
        await fail_job(job["_id"], f"no handler for kind={kind}")
        return
    try:
        result = await asyncio.wait_for(
            handler(job.get("payload", {})),
            timeout=job.get("timeout_seconds", 300),
        )
        await complete_job(job["_id"], result)
        logger.info("job %s (%s) completed", job["_id"][:8], kind)
    except asyncio.TimeoutError:
        await fail_job(job["_id"], f"timeout after {job.get('timeout_seconds', 300)}s")
        logger.warning("job %s (%s) timed out", job["_id"][:8], kind)
    except Exception as exc:
        await fail_job(job["_id"], str(exc)[:500])
        logger.error("job %s (%s) failed: %s", job["_id"][:8], kind, exc)


async def worker_loop(poll_interval: float = 2.0) -> None:
    logger.info("worker started")
    while not STOP.is_set():
        try:
            job = await claim_job()
            if job:
                await process_job(job)
            else:
                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("worker loop error: %s", exc)
            await asyncio.sleep(poll_interval)
    logger.info("worker stopped")


async def cleanup_loop(interval: int = 120) -> None:
    while not STOP.is_set():
        try:
            count = await cleanup_stale_jobs()
            if count:
                logger.info("cleaned up %d stale jobs", count)
        except Exception:
            pass
        await asyncio.sleep(interval)


def _handle_signal(sig, _frame):
    logger.info("received signal %s, shutting down", sig)
    STOP.set()


async def main() -> None:
    from app.core.db import connect_db, close_db
    from app.core.logging import configure_logging

    configure_logging()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    await connect_db()
    logger.info("connected to database")

    cleanup_task = asyncio.create_task(cleanup_loop())
    try:
        await worker_loop()
    finally:
        cleanup_task.cancel()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())