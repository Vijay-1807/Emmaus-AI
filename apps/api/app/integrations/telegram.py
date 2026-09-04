import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from pymongo.errors import DuplicateKeyError

from app.agents.orchestrator import run_investigation
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import hash_password

logger = logging.getLogger("vedax.telegram")

API_BASE = "https://api.telegram.org"
MAX_MESSAGE = 4000

# Free-tier protection: burst caps per chat (Groq 429s hurt everyone).
MAX_MSGS_PER_MINUTE = 8
RATE_WINDOW_SECONDS = 60
TELEGRAM_MAX_FILE_BYTES = 20 * 1024 * 1024


class TelegramApiError(RuntimeError):
    def __init__(self, error_code: int, description: str, retry_after: int | None = None):
        super().__init__(f"Telegram API {error_code}: {description}")
        self.error_code = error_code
        self.retry_after = retry_after

WELCOME_TEXT = (
    "👋 *Welcome to Emmaus AI*\n\n"
    "Send me text, documents, photos, handwriting or voice notes and I will "
    "investigate them with the full multimodal pipeline.\n\n"
    "Commands:\n"
    "/new — start a fresh chat\n"
    "/history — recent investigations\n"
    "/status — your workspace stats\n"
    "/help — this help"
)

HELP_TEXT = (
    "📖 *Emmaus AI help*\n\n"
    "Send any question — I search your documents, datasets, images and audio.\n"
    "Attach a file, photo or voice note with a caption to analyze it.\n"
    "/new — fresh chat (forgets previous context)\n"
    "/history — your recent investigations\n"
    "/status — documents, datasets and usage\n"
    "Answers arrive with a *Sources* button for citations."
)


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
        data = response.json()
        if not data.get("ok"):
            parameters = data.get("parameters") or {}
            raise TelegramApiError(
                int(data.get("error_code", response.status_code)),
                str(data.get("description", "Telegram request failed")),
                parameters.get("retry_after"),
            )
        return data


async def download_file(file_id: str) -> tuple[bytes, str]:
    settings = get_settings()
    result = await telegram_request("getFile", {"file_id": file_id})
    file_result = result.get("result") or {}
    file_size = int(file_result.get("file_size") or 0)
    if file_size > TELEGRAM_MAX_FILE_BYTES:
        raise ValueError("Telegram file exceeds the 20 MB bot processing limit")
    file_path = file_result.get("file_path")
    if not file_path:
        raise ValueError("Telegram did not return a downloadable file path")
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(
            f"{API_BASE}/file/bot{settings.telegram_bot_token}/{file_path}"
        )
        response.raise_for_status()
        data = response.content
        if len(data) > TELEGRAM_MAX_FILE_BYTES:
            raise ValueError("Telegram file exceeds the 20 MB bot processing limit")
        return data, file_path.rsplit("/", 1)[-1]


async def claim_update(update_id: int) -> bool:
    db = get_db()
    try:
        await db.telegram_updates.insert_one(
            {"update_id": update_id, "status": "processing", "created_at": now()}
        )
        return True
    except DuplicateKeyError:
        return False


async def process_claimed_update(update_id: int, update: dict) -> None:
    db = get_db()
    try:
        await handle_update(update)
        await db.telegram_updates.update_one(
            {"update_id": update_id}, {"$set": {"status": "completed", "completed_at": now()}}
        )
    except Exception as exc:
        logger.error("telegram update %s failed: %s", update_id, exc, exc_info=True)
        await db.telegram_updates.update_one(
            {"update_id": update_id},
            {"$set": {"status": "failed", "error": str(exc)[:500], "failed_at": now()}},
        )


async def send_message(
    chat_id: int, text: str, reply_markup: dict | None = None
) -> None:
    for start in range(0, len(text), MAX_MESSAGE):
        chunk = text[start : start + MAX_MESSAGE]
        payload: dict = {"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"}
        if reply_markup is not None and start + MAX_MESSAGE >= len(text):
            payload["reply_markup"] = reply_markup
        try:
            await telegram_request("sendMessage", payload)
        except TelegramApiError as exc:
            # Markdown parse errors are deterministic; transport/API errors
            # must not be blindly resent because Telegram may have accepted it.
            if exc.error_code not in (400,):
                raise
            payload.pop("parse_mode", None)
            payload.pop("reply_markup", None)
            await telegram_request("sendMessage", payload)


async def send_action(chat_id: int, action: str = "typing") -> None:
    try:
        await telegram_request("sendChatAction", {"chat_id": chat_id, "action": action})
    except Exception:
        pass


async def _typing_loop(chat_id: int, stop: asyncio.Event) -> None:
    """Keep the 'typing…' indicator alive during long investigations."""
    while not stop.is_set():
        await send_action(chat_id, "typing")
        try:
            await asyncio.wait_for(stop.wait(), timeout=4.0)
        except asyncio.TimeoutError:
            pass


def answer_keyboard(investigation_id: str | None = None) -> dict:
    buttons: list[dict] = []
    if investigation_id:
        buttons.append(
            {"text": "📄 Sources", "callback_data": f"sources:{investigation_id}"}
        )
    buttons.append({"text": "💬 New chat", "callback_data": "newchat"})
    return {"inline_keyboard": [buttons]}


async def check_rate_limit(link: dict) -> str | None:
    """Sliding-window burst cap + single-flight lock. Returns wait message or None."""
    db = get_db()
    if link.get("locked"):
        return "⏳ I'm still working on your previous question — one moment…"
    now_ts = now().timestamp()
    recent = [t for t in link.get("msg_times", []) if now_ts - t < RATE_WINDOW_SECONDS]
    if len(recent) >= MAX_MSGS_PER_MINUTE:
        wait = int(RATE_WINDOW_SECONDS - (now_ts - min(recent))) + 1
        return f"🐢 Slow down a little — try again in ~{wait}s (free-tier limits)."
    recent.append(now_ts)
    await db.telegram_links.update_one(
        {"_id": link["_id"]}, {"$set": {"msg_times": recent[-MAX_MSGS_PER_MINUTE:]}}
    )
    return None


async def set_locked(link_id: str, locked: bool) -> None:
    db = get_db()
    await db.telegram_links.update_one({"_id": link_id}, {"$set": {"locked": locked}})


async def claim_chat_lock(link_id: str, lease_seconds: int = 180) -> str | None:
    """Atomically claim one chat; leases recover after worker/process crashes."""
    db = get_db()
    token = uuid.uuid4().hex
    result = await db.telegram_links.update_one(
        {
            "_id": link_id,
            "$or": [
                {"locked": {"$ne": True}},
                {"lock_expires_at": {"$lt": now()}},
            ],
        },
        {
            "$set": {
                "locked": True,
                "lock_token": token,
                "lock_expires_at": now() + timedelta(seconds=lease_seconds),
            }
        },
    )
    return token if result.modified_count == 1 else None


async def release_chat_lock(link_id: str, token: str) -> None:
    db = get_db()
    await db.telegram_links.update_one(
        {"_id": link_id, "lock_token": token},
        {"$set": {"locked": False}, "$unset": {"lock_token": "", "lock_expires_at": ""}},
    )


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
    try:
        await db.telegram_links.insert_one(link)
        return link
    except DuplicateKeyError:
        # Another webhook delivery won the first-contact race. Remove only
        # this request's orphan records, then use the winner's link.
        await db.users.delete_one({"_id": user_id})
        await db.workspaces.delete_one({"_id": workspace_id})
        existing = await db.telegram_links.find_one({"telegram_chat_id": chat_id})
        if existing:
            return existing
        raise


async def wait_for_ingestion(collection: str, source_id: str, timeout_seconds: int = 90) -> None:
    """Telegram should not answer before an attached source is searchable."""
    db = get_db()
    deadline = now().timestamp() + timeout_seconds
    while now().timestamp() < deadline:
        source = await db[collection].find_one({"_id": source_id})
        if not source:
            raise ValueError("uploaded source disappeared during processing")
        if source.get("status") == "ready":
            return
        if source.get("status") == "failed":
            raise ValueError(source.get("error") or "source processing failed")
        await asyncio.sleep(0.5)
    raise TimeoutError("source processing timed out")


async def extract_question(
    message: dict, workspace_id: str, owner_id: str
) -> tuple[str, list[str], str | None]:
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
        if filename.lower().endswith((".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".xls")):
            data, _ = await download_file(document_info["file_id"])
            content_type = document_info.get("mime_type") or "application/octet-stream"
            from app.services.dataset_service import create_dataset
            from app.services.document_service import create_document

            try:
                if filename.lower().endswith((".csv", ".xlsx", ".xls")):
                    dataset = await create_dataset(
                        workspace_id, owner_id, filename, content_type, data
                    )
                    await wait_for_ingestion("datasets", dataset["_id"])
                    attachment_ids.append(dataset["_id"])
                else:
                    document = await create_document(
                        workspace_id, owner_id, filename, content_type, data
                    )
                    await wait_for_ingestion("documents", document["_id"])
                    attachment_ids.append(document["_id"])
                if not text:
                    text = f"Process and summarize {filename}"
            except Exception as exc:
                logger.warning("telegram document processing failed: %s", exc)

    return text, attachment_ids, audio_media_id


async def handle_command(chat_id: int, link: dict, command: str) -> bool:
    """Returns True if the text was a command (handled, skip investigation)."""
    db = get_db()
    workspace_id = link["workspace_id"]
    cmd = command.split()[0].split("@")[0]

    if cmd == "/start":
        await send_message(chat_id, WELCOME_TEXT)
        return True
    if cmd == "/help":
        await send_message(chat_id, HELP_TEXT)
        return True
    if cmd == "/new":
        if link.get("locked"):
            await send_message(chat_id, "⏳ Your current investigation is still running. Try /new when it finishes.")
            return True
        await db.telegram_links.update_one(
            {"_id": link["_id"]},
            {"$set": {"conversation_id": None, "last_investigation_id": None}},
        )
        await send_message(chat_id, "💬 Fresh chat started — previous context cleared.")
        return True
    if cmd == "/history":
        cursor = (
            db.investigations.find({"workspace_id": workspace_id})
            .sort("created_at", -1)
            .limit(5)
        )
        lines = []
        async for inv in cursor:
            q = (inv.get("question") or "(untitled)").strip()
            if len(q) > 60:
                q = q[:57] + "…"
            lines.append(f"• {q}")
        await send_message(
            chat_id,
            "🕘 *Recent investigations*\n\n" + ("\n".join(lines) if lines else "Nothing yet — ask me anything!"),
        )
        return True
    if cmd == "/status":
        docs = await db.documents.count_documents({"workspace_id": workspace_id})
        datasets = await db.datasets.count_documents({"workspace_id": workspace_id})
        media = await db.media_assets.count_documents({"workspace_id": workspace_id})
        convs = await db.conversations.count_documents({"workspace_id": workspace_id})
        await send_message(
            chat_id,
            f"📊 *Your workspace*\n\nDocuments: {docs}\nDatasets: {datasets}\n"
            f"Media: {media}\nConversations: {convs}",
        )
        return True
    return False


def format_citations(investigation: dict) -> str:
    citations = investigation.get("citations") or []
    if not citations:
        return "No citations recorded for this answer."
    lines = ["📄 *Sources*"]
    for i, cite in enumerate(citations[:10], start=1):
        name = cite.get("document_name", "source") if isinstance(cite, dict) else str(cite)
        page = cite.get("page") if isinstance(cite, dict) else None
        lines.append(f"{i}. {name}" + (f" (p. {page})" if page else ""))
    return "\n".join(lines)


async def handle_callback(update: dict) -> None:
    query = update.get("callback_query") or {}
    data = query.get("data", "")
    chat = (query.get("message") or {}).get("chat", {})
    chat_id = chat.get("id")
    if not chat_id:
        return
    try:
        await telegram_request(
            "answerCallbackQuery", {"callback_query_id": query.get("id")}
        )
    except Exception:
        pass
    db = get_db()
    link = await db.telegram_links.find_one({"telegram_chat_id": chat_id})
    if not link:
        return
    if data == "newchat":
        if link.get("locked"):
            await send_message(chat_id, "⏳ Your current investigation is still running. Try /new when it finishes.")
            return
        await db.telegram_links.update_one(
            {"_id": link["_id"]},
            {"$set": {"conversation_id": None, "last_investigation_id": None}},
        )
        await send_message(chat_id, "💬 Fresh chat started — previous context cleared.")
    elif data.startswith("sources:"):
        inv_id = data.split(":", 1)[1]
        inv = await db.investigations.find_one(
            {"_id": inv_id, "workspace_id": link["workspace_id"]}
        )
        await send_message(
            chat_id, format_citations(inv) if inv else "Sources expired — ask again to refresh."
        )


async def handle_update(update: dict) -> None:
    if update.get("callback_query"):
        await handle_callback(update)
        return
    message = update.get("message") or update.get("edited_message")
    if not message:
        return
    chat_id = message["chat"]["id"]
    if message.get("chat", {}).get("type", "private") != "private":
        await send_message(chat_id, "For privacy, Emmaus AI currently works in private chats only.")
        return
    link = await get_or_create_link(chat_id, message.get("from", {}))
    workspace_id = link["workspace_id"]

    text = (message.get("text") or "").strip()
    if text.startswith("/"):
        if await handle_command(chat_id, link, text):
            return
        await send_message(chat_id, "Unknown command. Try /help.")
        return

    limited = await check_rate_limit(link)
    if limited:
        await send_message(chat_id, limited)
        return

    lock_token = await claim_chat_lock(link["_id"])
    if not lock_token:
        await send_message(chat_id, "⏳ I'm still working on your previous question — one moment…")
        return
    await send_action(chat_id, "typing")
    try:
        text, attachment_ids, audio_media_id = await extract_question(
            message, workspace_id, link["user_id"]
        )
        if not text and not attachment_ids and not audio_media_id:
            await send_message(chat_id, "I could not read this message type.")
            await release_chat_lock(link["_id"], lock_token)
            return
        if not text:
            text = "Explain this."
    except Exception as exc:
        await send_message(chat_id, f"I could not process that attachment: {str(exc)[:180]}")
        await release_chat_lock(link["_id"], lock_token)
        return

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_typing_loop(chat_id, stop_typing))
    final_answer = ""
    investigation_id: str | None = None
    try:
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
                investigation_id = event["investigation"].get("id")
                new_conversation = event["investigation"]["conversation_id"]
                db = get_db()
                updates: dict = {"last_investigation_id": investigation_id}
                if new_conversation != conversation_id:
                    updates["conversation_id"] = new_conversation
                await db.telegram_links.update_one({"_id": link["_id"]}, {"$set": updates})
            elif event["type"] == "error":
                final_answer = event["message"]
    finally:
        stop_typing.set()
        try:
            await typing_task
        except Exception:
            pass
        await release_chat_lock(link["_id"], lock_token)
    await send_message(
        chat_id,
        final_answer or "Something went wrong. Please try again.",
        reply_markup=answer_keyboard(investigation_id),
    )


async def webhook_info() -> dict:
    result = await telegram_request("getWebhookInfo", {})
    return result.get("result", {})
