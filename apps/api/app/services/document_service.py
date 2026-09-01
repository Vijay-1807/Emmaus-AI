import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.core.db import get_db
from app.ingestion.chunker import chunk_document
from app.ingestion.indexer import delete_document_chunks, index_chunks
from app.ingestion.parser import detect_source_type, parse_document
from app.rag.embeddings import get_embedding_service
from app.services.media_service import MediaService
from app.vision.analyzer import analyze_image, format_analysis_for_indexing, ocr_image

logger = logging.getLogger("vedax.documents")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".oga", ".webm", ".flac"}
DOC_EXTS = {".pdf", ".docx", ".txt", ".md", ".markdown"}
ALLOWED_EXTS = DOC_EXTS | IMAGE_EXTS | AUDIO_EXTS


def now() -> datetime:
    return datetime.now(timezone.utc)


def validate_upload(filename: str, size: int) -> str:
    settings = get_settings()
    if size > settings.max_upload_bytes:
        raise ValueError(f"file exceeds {settings.max_upload_mb}MB limit")
    lower = filename.lower()
    if not any(lower.endswith(ext) for ext in ALLOWED_EXTS):
        raise ValueError(
            f"unsupported file type: {filename}. Allowed: pdf, docx, txt, md, "
            "jpg, png, webp, csv, xlsx, wav, mp3, m4a, ogg"
        )
    return detect_source_type(filename, "")


async def create_document(
    workspace_id: str, owner_id: str, filename: str, content_type: str, data: bytes
) -> dict:
    db = get_db()
    source_type = validate_upload(filename, len(data))
    media = MediaService()
    resource_kind = {"image": "image", "audio": "audio", "document": "file"}[source_type]
    stored = await media.upload(data, filename, workspace_id, resource_kind)
    document = {
        "_id": uuid.uuid4().hex,
        "workspace_id": workspace_id,
        "owner_id": owner_id,
        "filename": filename,
        "content_type": content_type or "application/octet-stream",
        "source_type": source_type,
        "status": "processing",
        "error": None,
        "num_chunks": 0,
        "num_pages": 0,
        "size_bytes": len(data),
        "analysis": None,
        "transcript": None,
        "media": {
            "url": stored.url,
            "public_id": stored.public_id,
            "mode": stored.mode,
            "resource_type": stored.resource_type,
        },
        "created_at": now(),
    }
    await db.documents.insert_one(document)
    asyncio.create_task(
        _process_document(
            document["_id"], workspace_id, filename, content_type, data
        )
    )
    return document


async def _process_document(
    document_id: str, workspace_id: str, filename: str, content_type: str, data: bytes
) -> None:
    db = get_db()
    try:
        parsed = parse_document(filename, content_type, data)
        analysis = None
        transcript = None

        if parsed.source_type == "image":
            analysis = await analyze_image(data, content_type or "image/png")
            text = format_analysis_for_indexing(filename, analysis)
            parsed.pages = [
                {"number": 1, "text": text, "headings": []}
            ]
        elif parsed.source_type == "audio":
            from app.audio.transcriber import transcribe_audio

            result = await transcribe_audio(data, filename, content_type)
            transcript = result["text"]
            parsed.pages = [
                {"number": 1, "text": f"Audio transcript ({filename}):\n{transcript}", "headings": []}
            ]
        else:
            for page in parsed.pages:
                if page.needs_ocr and page.render_png:
                    ocr = await ocr_image(page.render_png, "image/png")
                    if ocr.get("text"):
                        page.text = ocr["text"]
                        page.needs_ocr = False
            for table in parsed.tables:
                if table.get("records"):
                    parsed.pages.append(
                        {
                            "number": parsed.pages[-1].number if parsed.pages else 1,
                            "text": _table_to_text(table),
                            "headings": [],
                        }
                    )
            pages = [
                p if isinstance(p, dict) else {"number": p.number, "text": p.text, "headings": p.headings}
                for p in parsed.pages
            ]

        chunks = chunk_document(pages)
        embedding_service = get_embedding_service()
        num_chunks = await index_chunks(
            workspace_id,
            document_id,
            filename,
            parsed.source_type,
            chunks,
            embedding_service,
            embedding_service.settings.embedding_model,
        )
        await db.documents.update_one(
            {"_id": document_id},
            {
                "$set": {
                    "status": "ready",
                    "num_chunks": num_chunks,
                    "num_pages": len(parsed.pages),
                    "analysis": analysis,
                    "transcript": transcript,
                }
            },
        )
        logger.info("document %s processed (%s chunks)", document_id, num_chunks)
    except Exception as exc:
        logger.error("document processing failed: %s", exc, exc_info=True)
        await db.documents.update_one(
            {"_id": document_id},
            {"$set": {"status": "failed", "error": str(exc)[:500]}},
        )


def _table_to_text(table: dict) -> str:
    columns = table.get("columns", [])
    lines = [" | ".join(str(c) for c in columns)]
    for row in table.get("rows", [])[1:51]:
        lines.append(" | ".join(str(c) for c in row))
    return "\n".join(lines)


async def list_documents(workspace_id: str, limit: int = 100) -> list[dict]:
    db = get_db()
    cursor = (
        db.documents.find({"workspace_id": workspace_id})
        .sort("created_at", -1)
        .limit(limit)
    )
    return [doc async for doc in cursor]


async def get_document(workspace_id: str, document_id: str) -> dict | None:
    db = get_db()
    return await db.documents.find_one({"_id": document_id, "workspace_id": workspace_id})


async def delete_document(workspace_id: str, document_id: str) -> bool:
    db = get_db()
    document = await get_document(workspace_id, document_id)
    if not document:
        return False
    await delete_document_chunks(document_id)
    media_info = document.get("media")
    if media_info and media_info.get("mode") == "local":
        local_path = Path("media") / media_info["public_id"].split("/", 1)[1]
        local_path.unlink(missing_ok=True)
    elif media_info and media_info.get("mode") == "cloudinary":
        try:
            import cloudinary.api

            media = MediaService()
            media._configure_cloudinary()
            await asyncio.to_thread(
                cloudinary.api.delete_asset,
                media_info["public_id"],
                resource_type=media_info.get("resource_type", "raw"),
            )
        except Exception:
            logger.warning("cloudinary delete failed for %s", media_info.get("public_id"))
    await db.documents.delete_one({"_id": document_id})
    return True
