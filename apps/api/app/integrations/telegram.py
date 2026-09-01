import logging
import uuid
from datetime import datetime, timezone

import httpx

from app.agents.orchestrator import run_investigation
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import hash_password

logger = logging.getLogger("vedax.telegram")

API_BASE = "https://api.telegram.org"
MAX_MESSAGE = 4000


def now() -> datetime:
    return datetime.now(timezone.utc)


async def telegram_request(method: str, payload: dict) -> dict:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not configured")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{API_BASE}/bot{settings.telegram_bot_token}/{method}", json=payload
        )
        response.raise_for_status()
        return response.json()


async def download_file(file_id: str) -> tuple[bytes, str]:
    settings = get_settings()
    result = await telegram_request("getFile", {"file_id": file_id})
    file_path = result["result"]["file_path"]
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(
            f"{API_BASE}/file/bot{settings.telegram_bot_token}/{file_path}"
        )
        response.raise_for_status()
        return response.content, file_path.rsplit("/", 1)[-1]


async def send_message(chat_id: int, text: str) -> None:
    for start in range(0, len(text), MAX_MESSAGE):
        chunk = text[start : start + MAX_MESSAGE]
        try:
            await telegram_request(
                "sendMessage",
                {"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"},
            )
        except Exception:
            await telegram_request("sendMessage", {"chat_id": chat_id, "text": chunk})


async def get_or_create_link(chat_id: int, from_user: dict) -> dict:
    db = get_db()
    link = await db.telegram_links.find_one({"telegram_chat_id": chat_id})
    if link:
        return link
    user_id = uuid.uuid4().hex
    await db.users.insert_one(
        {
            "_id": user_id,
            "email": f"tg-{chat_id}@telegram.vedax.local",
            "name": from_user.get("first_name", "Telegram User"),
            "password_hash": hash_password(uuid.uuid4().hex),
            "created_at": now(),
        }
    )
    workspace_id = uuid.uuid4().hex
    await db.workspaces.insert_one(
        {
            "_id": workspace_id,
            "name": "Telegram",
            "description": "Auto-provisioned workspace for Telegram chats",
            "owner_id": user_id,
            "created_at": now(),
        }
    )
    link = {
        "_id": uuid.uuid4().hex,
        "telegram_chat_id": chat_id,
        "user_id": user_id,
        "workspace_id": workspace_id,
        "created_at": now(),
    }
    await db.telegram_links.insert_one(link)
    return link


async def extract_question(message: dict, workspace_id: str) -> tuple[str, list[str], str | None]:
    text = (message.get("text") or message.get("caption") or "").strip()
    attachment_ids: list[str] = []
    audio_media_id = None
    db = get_db()

    if message.get("voice") or message.get("audio"):
        file_info = message.get("voice") or message.get("audio")
        data, filename = await download_file(file_info["file_id"])
        from app.services.media_service import MediaService

        media_service = MediaService()
        stored = await media_service.upload(data, filename, workspace_id, "audio")
        from app.audio.transcriber import transcribe_audio

        transcript = ""
        try:
            transcript = (await transcribe_audio(data, filename))["text"]
        except Exception as exc:
            logger.warning("telegram voice transcription failed: %s", exc)
        media = {
            "_id": uuid.uuid4().hex,
            "workspace_id": workspace_id,
            "kind": "audio",
            "filename": filename,
            "url": stored.url,
            "public_id": stored.public_id,
            "storage_mode": stored.mode,
            "transcript": transcript or None,
            "analysis": None,
            "size_bytes": len(data),
            "created_at": now(),
        }
        await db.media_assets.insert_one(media)
        audio_media_id = media["_id"]
        if not text:
            text = transcript or "(unintelligible voice message)"

    for photo in (message.get("photo") or [])[-1:]:
        data, filename = await download_file(photo["file_id"])
        from app.services.media_service import MediaService

        media_service = MediaService()
        stored = await media_service.upload(data, filename, workspace_id, "image")
        from app.vision.analyzer import analyze_image

        analysis = None
        try:
            analysis = await analyze_image(data, "image/jpeg")
        except Exception as exc:
            logger.warning("telegram photo analysis failed: %s", exc)
        media = {
            "_id": uuid.uuid4().hex,
            "workspace_id": workspace_id,
            "kind": "image",
            "filename": filename,
            "url": stored.url,
            "public_id": stored.public_id,
            "storage_mode": stored.mode,
            "transcript": None,
            "analysis": analysis,
            "size_bytes": len(data),
            "created_at": now(),
        }
        await db.media_assets.insert_one(media)
        attachment_ids.append(media["_id"])

    if message.get("document"):
        document_info = message["document"]
        filename = document_info.get("file_name", "file")
        if filename.lower().endswith((".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx")):
            data, _ = await download_file(document_info["file_id"])
            from app.services.dataset_service import create_dataset
            from app.services.document_service import create_document

            try:
                if filename.lower().endswith((".csv", ".xlsx", ".xls")):
                    dataset = await create_dataset(
                        workspace_id, "telegram", filename, "application/octet-stream", data
                    )
                    attachment_ids.append(dataset["_id"])
                else:
                    document = await create_document(
                        workspace_id, "telegram", filename, "application/octet-stream", data
                    )
                    attachment_ids.append(document["_id"])
                if not text:
                    text = f"Process and summarize {filename}"
            except Exception as exc:
                logger.warning("telegram document processing failed: %s", exc)

    return text, attachment_ids, audio_media_id


async def handle_update(update: dict) -> None:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return
    chat_id = message["chat"]["id"]
    link = await get_or_create_link(chat_id, message.get("from", {}))
    workspace_id = link["workspace_id"]

    if (message.get("text") or "").startswith("/start"):
        await send_message(
            chat_id,
            "Welcome to VedaX AI. Send me text, documents, photos, handwriting or voice notes "
            "and I will investigate them with the full multimodal pipeline.",
        )
        return

    text, attachment_ids, audio_media_id = await extract_question(message, workspace_id)
    if not text and not attachment_ids and not audio_media_id:
        await send_message(chat_id, "I could not read this message type.")
        return
    if not text:
        text = "Explain this."

    final_answer = ""
    conversation_id = link.get("conversation_id")
    async for event in run_investigation(
        workspace_id=workspace_id,
        user_id=link["user_id"],
        question=text,
        conversation_id=conversation_id,
        attachment_ids=attachment_ids,
        audio_media_id=audio_media_id,
    ):
        if event["type"] == "done":
            final_answer = event["investigation"]["answer"]
            new_conversation = event["investigation"]["conversation_id"]
            if new_conversation != conversation_id:
                db = get_db()
                await db.telegram_links.update_one(
                    {"_id": link["_id"]}, {"$set": {"conversation_id": new_conversation}}
                )
        elif event["type"] == "error":
            final_answer = event["message"]
    await send_message(chat_id, final_answer or "Something went wrong. Please try again.")


async def webhook_info() -> dict:
    result = await telegram_request("getWebhookInfo", {})
    return result.get("result", {})
