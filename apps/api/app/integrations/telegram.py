import asyncio
import logging
import re
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

# GPT-OSS citation tokens (【1†L2-L3】), bracketed refs, confidence lines,
# and Unicode narrow spaces that Telegram renders oddly.
_CITATION_TOKEN_RE = re.compile(
    r"【[^】]*】|\[\d+†[^\]]*\]|\[\^?\d+(?:\s*,\s*\^?\d+)*\]"
)
_UNICODE_SPACE_RE = re.compile(
    r"[\u00a0\u202f\u2009\u2007\u2002\u2003\u2004\u2005\u2006\u2008\u205f]"
)
_CONFIDENCE_LINE_RE = re.compile(r"^\s*Confidence:\s*.*$", re.IGNORECASE | re.MULTILINE)


_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```")
_SOURCE_SECTION_RE = re.compile(r"\n+Sources?:\s*\n[\s\S]*$", re.IGNORECASE)
_REFERENCE_SECTION_RE = re.compile(r"\n+References?:\s*\n[\s\S]*$", re.IGNORECASE)


_IMAGE_INTENT_RE = re.compile(
    r"\b(generate|create|make|draw|need|want).{0,30}\bimages?\b"
    r"|\bimages?\b(.{0,20}\b(of|for|please)\b|[.!?,]*$)",
    re.IGNORECASE,
)


def maybe_add_image_hint(question: str, has_attachments: bool) -> str:
    """Nudge users toward /generate when plain text asks for an image.

    Plain-text image wishes otherwise trigger a full RAG investigation,
    which is slow and never returns a picture.
    """
    if has_attachments:
        return ""
    if _IMAGE_INTENT_RE.search(question or ""):
        return "\n\n🎨 _Want me to create this as an image? Use /generate <prompt>_"
    return ""


def clean_answer_for_telegram(text: str) -> str:
    """Mirror the website's answer cleaning so Telegram gets the same polish."""
    cleaned = _CITATION_TOKEN_RE.sub("", text)
    cleaned = _UNICODE_SPACE_RE.sub(" ", cleaned)
    cleaned = _CONFIDENCE_LINE_RE.sub("", cleaned)
    cleaned = _SOURCE_SECTION_RE.sub("", cleaned)
    cleaned = _REFERENCE_SECTION_RE.sub("", cleaned)
    cleaned = _CODE_FENCE_RE.sub("", cleaned)
    cleaned = cleaned.replace("\u2014", "-").replace("\u2013", "-")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()

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
    "I can search your documents, analyze datasets, read images, and transcribe voice.\n\n"
    "💡 *Try asking:*\n"
    "• \"Summarize my uploaded documents\"\n"
    "• \"What are the key insights in my dataset?\"\n"
    "• \"Analyze this photo\"\n\n"
    "📎 *Tips:* Attach a file with a caption, or use /generate <prompt> for AI images.\n\n"
    "Commands: /new  /stop  /clear  /history  /status  /generate  /help"
)

HELP_TEXT = (
    "📖 *Emmaus AI — Help*\n\n"
    "*Ask:*\n"
    "• Type any question about your sources.\n"
    "• Attach a doc (PDF/DOCX/TXT/MD), dataset (CSV/XLSX/XLS), photo, or voice note — with or without a caption.\n\n"
    "*Commands:*\n"
    "• /new — fresh chat (clears conversation memory)\n"
    "• /stop — cancel a running investigation\n"
    "• /clear — wipe all workspace data (docs, datasets, history)\n"
    "• /history — last 5 investigations\n"
    "• /status — your docs / datasets / media / chats\n"
    "• /generate <prompt> — generate an image with AI\n"
    "• /help — this help\n\n"
    "💡 *Tip:* After an answer, tap *Sources* to see citations, *New chat* to reset."
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
        # Try to notify the user
        try:
            message = update.get("message") or update.get("callback_query", {}).get("message", {})
            chat_id = message.get("chat", {}).get("id")
            if chat_id:
                await send_message(chat_id, "❌ Something went wrong processing your message. Please try again.")
        except Exception:
            pass
        await db.telegram_updates.update_one(
            {"update_id": update_id},
            {"$set": {"status": "failed", "error": str(exc)[:500], "failed_at": now()}},
        )


def _chunk_message(text: str, limit: int = MAX_MESSAGE) -> list[str]:
    """Split on paragraph boundaries so markdown/code/citations stay intact."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    for block in text.split("\n\n"):
        if len(block) + 2 <= limit and parts and len(parts[-1]) + 2 + len(block) <= limit:
            parts[-1] = f"{parts[-1]}\n\n{block}"
        elif len(block) <= limit:
            parts.append(block)
        else:
            for line in block.split("\n"):
                if len(line) <= limit:
                    if parts and len(parts[-1]) + 1 + len(line) <= limit:
                        parts[-1] = f"{parts[-1]}\n{line}"
                    else:
                        parts.append(line)
                else:
                    for i in range(0, len(line), limit):
                        parts.append(line[i : i + limit])
    return parts


async def send_message(
    chat_id: int, text: str, reply_markup: dict | None = None
) -> None:
    chunks = _chunk_message(text)
    for i, chunk in enumerate(chunks):
        payload: dict = {"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"}
        if reply_markup is not None and i == len(chunks) - 1:
            payload["reply_markup"] = reply_markup
        try:
            await telegram_request("sendMessage", payload)
        except TelegramApiError as exc:
            if exc.error_code not in (400,):
                raise
            # Markdown failed — try HTML fallback, then plain text.
            # Always preserve reply_markup (buttons are JSON, not Markdown).
            html_text = (
                chunk.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            # Convert Markdown bold/italic/code to HTML
            html_text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html_text)
            html_text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", html_text)
            html_text = re.sub(r"`(.+?)`", r"<code>\1</code>", html_text)
            payload["text"] = html_text
            payload["parse_mode"] = "HTML"
            try:
                await telegram_request("sendMessage", payload)
            except TelegramApiError:
                # HTML also failed — send plain text, still keep buttons
                payload["text"] = chunk
                payload.pop("parse_mode", None)
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


def persistent_keyboard() -> dict:
    """Bottom reply-keyboard so commands are always one tap away (not a slash)."""
    return {
        "keyboard": [
            [{"text": "/status"}, {"text": "/history"}, {"text": "/new"}, {"text": "/clear"}],
            [{"text": "/generate"}, {"text": "/stop"}, {"text": "/help"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


async def check_rate_limit(link: dict) -> str | None:
    """Sliding-window burst cap + single-flight lock. Returns wait message or None.
    
    Uses atomic MongoDB operations to prevent race conditions.
    """
    db = get_db()
    link_id = link["_id"]
    
    # First, atomically check and clear stale locks
    if link.get("locked"):
        expires = link.get("lock_expires_at")
        if expires is not None:
            # Mongo returns naive datetimes; normalize before comparing.
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= now():
                # Stale lock from a crashed run — clear it atomically
                result = await db.telegram_links.update_one(
                    {
                        "_id": link_id,
                        "locked": True,
                        "lock_expires_at": {"$lte": expires},
                    },
                    {
                        "$set": {"locked": False},
                        "$unset": {"lock_token": "", "lock_expires_at": ""},
                    },
                )
                if result.modified_count == 1:
                    link["locked"] = False
                else:
                    # Another process cleared it
                    return "⏳ Still working on your previous question — one moment…"
            else:
                return "⏳ Still working on your previous question — one moment…"
        else:
            return "⏳ I'm still working on your previous question — one moment…"
    
    # Atomically check rate limit and append timestamp
    now_ts = now().timestamp()
    cutoff_ts = now_ts - RATE_WINDOW_SECONDS
    
    # Use atomic MongoDB operation to:
    # 1. Remove old timestamps outside the window
    # 2. Add the new timestamp
    # 3. Keep only the last MAX_MSGS_PER_MINUTE timestamps
    result = await db.telegram_links.update_one(
        {
            "_id": link_id,
            "$or": [
                {"msg_times": {"$exists": False}},
                {"msg_times.0": {"$lt": cutoff_ts}},  # At least one old timestamp
                {"$expr": {"$lt": [{"$size": "$msg_times"}, MAX_MSGS_PER_MINUTE]}},  # Under limit
            ],
        },
        {
            "$push": {
                "msg_times": {
                    "$each": [now_ts],
                    "$slice": -MAX_MSGS_PER_MINUTE,  # Keep only last N
                }
            },
        },
    )
    
    if result.modified_count == 0:
        # Rate limit exceeded - get current count to calculate wait
        updated_link = await db.telegram_links.find_one({"_id": link_id})
        recent = [t for t in (updated_link or {}).get("msg_times", []) if now_ts - t < RATE_WINDOW_SECONDS]
        if len(recent) >= MAX_MSGS_PER_MINUTE:
            wait = int(RATE_WINDOW_SECONDS - (now_ts - min(recent))) + 1
            return f"🐢 Too many messages at once — try again in ~{wait}s."
    
    return None


async def set_locked(link_id: str, locked: bool) -> None:
    db = get_db()
    await db.telegram_links.update_one({"_id": link_id}, {"$set": {"locked": locked}})


async def claim_chat_lock(link_id: str, lease_seconds: int = 320) -> str | None:
    """Atomically claim one chat; leases recover after worker/process crashes.

    Lease (320s) covers the 300s investigation timeout so the lock cannot
    expire mid-investigation and allow a concurrent overlapping run.
    """
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


def _is_locked(link: dict) -> bool:
    """True only if a lock is held AND its lease has not expired.

    The link dict is a snapshot taken at message start, so a boolean-only
    check would block /new and /clear even when the lock already expired.
    """
    if not link.get("locked"):
        return False
    expires = link.get("lock_expires_at")
    if expires is None:
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > now()


# Tracks live investigation tasks per chat so /stop and /clear can cancel
# a runaway investigation instead of waiting out the 300s timeout.
# Best-effort per process; the lock release below works cross-process anyway.
_RUNNING_TASKS: dict[int, asyncio.Task] = {}


async def _cancel_running(chat_id: int) -> bool:
    """Cancel the live investigation for a chat. Returns True if one was running."""
    task = _RUNNING_TASKS.pop(chat_id, None)
    if task is not None and not task.done():
        task.cancel()
        return True
    return False


async def _force_unlock(link_id: str) -> None:
    """Release a chat lock unconditionally (escape hatch for stuck runs)."""
    db = get_db()
    await db.telegram_links.update_one(
        {"_id": link_id},
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
            "email": f"tg-{chat_id}@telegram.emmaus.local",
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
    message: dict, workspace_id: str, owner_id: str, chat_id: int | None = None
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
            transcript = ""
        media = {
            "_id": uuid.uuid4().hex,
            "workspace_id": workspace_id,
            "kind": "audio",
            "filename": filename,
            "url": stored.url,
            "public_id": stored.public_id,
            "storage_mode": stored.mode,
            "bytes_path": stored.bytes_path,
            "transcript": transcript or None,
            "analysis": None,
            "size_bytes": len(data),
            "created_at": now(),
        }
        await db.media_assets.insert_one(media)
        audio_media_id = media["_id"]
        if not text:
            text = transcript or "(Could not transcribe voice — please type your question)"

    for photo in (message.get("photo") or [])[-1:]:
        data, _ = await download_file(photo["file_id"])
        from app.services.media_service import MediaService

        media_service = MediaService()
        caption = (message.get("caption") or "").strip()[:30] or "photo"
        safe_caption = re.sub(r"[^\w\s-]", "", caption).strip().replace(" ", "_") or "photo"
        filename = f"{safe_caption}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.jpg"
        stored = await media_service.upload(data, filename, workspace_id, "image")
        from app.vision.analyzer import analyze_image

        analysis = None
        try:
            analysis = await analyze_image(data, "image/jpeg")
        except Exception as exc:
            logger.warning("telegram photo analysis failed: %s", exc)
            if chat_id:
                await send_message(chat_id, "⚠️ Image analysis partially failed — I'll do my best with the text question.")
        media = {
            "_id": uuid.uuid4().hex,
            "workspace_id": workspace_id,
            "kind": "image",
            "filename": filename,
            "url": stored.url,
            "public_id": stored.public_id,
            "storage_mode": stored.mode,
            "bytes_path": stored.bytes_path,
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
                await send_message(chat_id, f"⚠️ Could not process `{filename}`: {str(exc)[:150]}")

    return text, attachment_ids, audio_media_id


async def handle_command(chat_id: int, link: dict, command: str) -> bool:
    """Returns True if the text was a command (handled, skip investigation)."""
    db = get_db()
    workspace_id = link["workspace_id"]
    cmd = command.split()[0].split("@")[0]

    if cmd == "/start":
        await send_message(chat_id, WELCOME_TEXT, reply_markup=persistent_keyboard())
        return True
    if cmd == "/generate":
        # Extract prompt from the command
        prompt = command[len("/generate"):].strip()
        if not prompt:
            await send_message(
                chat_id,
                "🎨 *Image Generation*\n\n"
                "Usage: /generate <prompt>\n"
                "Example: /generate A futuristic city at sunset\n\n"
                "The image will be generated using FLUX.1 Schnell model.",
            )
            return True
        
        # Check if Cloudflare is configured
        from app.core.config import get_settings
        settings = get_settings()
        if not settings.has_cloudflare:
            await send_message(
                chat_id,
                "❌ Image generation is not configured. "
                "Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN to enable this feature.",
            )
            return True
        
        # Generate image
        await send_action(chat_id, "upload_photo")
        try:
            from app.services.image_service import get_image_service
            import base64
            
            service = get_image_service()
            result = await service.generate(prompt=prompt)
            
            if not result.success:
                await send_message(chat_id, f"❌ Image generation failed: {result.error}")
                return True
            
            # Decode base64 image
            image_data = base64.b64decode(result.image_base64)
            
            # Send photo via Telegram API
            settings = get_settings()
            async with httpx.AsyncClient(timeout=60) as client:
                # Upload the image
                files = {"photo": ("generated_image.png", image_data, "image/png")}
                # Escape Markdown special chars in user prompt for caption
                safe_prompt = re.sub(r"([*_`\[\]])", r"\\\1", prompt[:200])
                payload = {
                    "chat_id": chat_id,
                    "caption": f"🎨 Generated Image\n\nPrompt: {safe_prompt}",
                }
                response = await client.post(
                    f"{API_BASE}/bot{settings.telegram_bot_token}/sendPhoto",
                    data=payload,
                    files=files,
                )
                response.raise_for_status()
            
        except Exception as exc:
            logger.error("Telegram image generation failed: %s", exc, exc_info=True)
            await send_message(chat_id, "❌ Image generation failed — please try again or use a different prompt.")
        return True
    if cmd == "/help":
        await send_message(chat_id, HELP_TEXT)
        return True
    if cmd == "/new":
        if _is_locked(link):
            await send_message(chat_id, "⏳ Still working on your previous question — send /stop to cancel it, or try /new in a moment.")
            return True
        await db.telegram_links.update_one(
            {"_id": link["_id"]},
            {"$set": {"conversation_id": None, "last_investigation_id": None}},
        )
        await send_message(chat_id, "💬 Fresh chat started — previous context cleared.")
        return True
    if cmd == "/stop":
        cancelled = await _cancel_running(chat_id)
        await _force_unlock(link["_id"])
        await send_message(
            chat_id,
            "⏹ Stopped the running investigation." if cancelled else "Nothing running — ask me anything!",
        )
        return True
    if cmd == "/clear":
        # Escape hatch: cancel any running investigation and force-unlock first,
        # otherwise a stuck run would block the very command meant to reset it.
        await _cancel_running(chat_id)
        await _force_unlock(link["_id"])
        # Wipe all workspace data
        db = get_db()
        ws = workspace_id
        docs = await db.documents.delete_many({"workspace_id": ws})
        datasets = await db.datasets.delete_many({"workspace_id": ws})
        media = await db.media_assets.delete_many({"workspace_id": ws})
        convs = await db.conversations.delete_many({"workspace_id": ws})
        invs = await db.investigations.delete_many({"workspace_id": ws})
        await db.telegram_links.update_one(
            {"_id": link["_id"]},
            {"$set": {"conversation_id": None, "last_investigation_id": None}},
        )
        total = docs.deleted_count + datasets.deleted_count + media.deleted_count + convs.deleted_count + invs.deleted_count
        await send_message(
            chat_id,
            f"🗑️ *Workspace cleared*\n\n"
            f"Deleted: {docs.deleted_count} docs, {datasets.deleted_count} datasets, "
            f"{media.deleted_count} media, {convs.deleted_count} conversations, "
            f"{invs.deleted_count} investigations.\n\n"
            f"Start fresh — upload a file or ask a question!",
        )
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
            "🕘 *Recent investigations*\n\n"
            + ("\n".join(lines) if lines else "Nothing yet — ask me anything!")
            + ("\n\n💬 Ask again to revisit any topic. Use /clear to wipe history." if lines else ""),
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
    if len(citations) > 10:
        lines.append(f"\n_...and {len(citations) - 10} more sources_")
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
            "answerCallbackQuery",
            {"callback_query_id": query.get("id"), "text": "Loading...", "show_alert": False},
        )
    except Exception:
        pass
    db = get_db()
    link = await db.telegram_links.find_one({"telegram_chat_id": chat_id})
    if not link:
        return
    if data == "newchat":
        if _is_locked(link):
            await send_message(chat_id, "⏳ Still working on your previous question — send /stop to cancel it.")
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


async def _collect_investigation(
    workspace_id: str,
    user_id: str,
    question: str,
    conversation_id: str | None,
    attachment_ids: list[str],
    audio_media_id: str | None,
) -> dict:
    """Collect all events from run_investigation into a single result dict."""
    result: dict = {"answer": "", "id": None, "conversation_id": conversation_id}
    async for event in run_investigation(
        workspace_id=workspace_id,
        user_id=user_id,
        question=question,
        conversation_id=conversation_id,
        attachment_ids=attachment_ids,
        audio_media_id=audio_media_id,
    ):
        if event["type"] == "done":
            result["answer"] = event["investigation"]["answer"]
            result["id"] = event["investigation"].get("id")
            result["conversation_id"] = event["investigation"]["conversation_id"]
        elif event["type"] == "error":
            result["answer"] = event["message"]
    return result


async def handle_update(update: dict) -> None:
    if update.get("callback_query"):
        await handle_callback(update)
        return
    message = update.get("message") or update.get("edited_message")
    if not message:
        return
    chat_id = message["chat"]["id"]
    # Ignore edited messages to avoid re-triggering investigations
    if update.get("edited_message"):
        return
    if message.get("chat", {}).get("type", "private") != "private":
        return  # Silently ignore group chats
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
        # Force-clear stale locks older than 5 minutes so user isn't stuck forever
        _db = get_db()
        stale = await _db.telegram_links.find_one({
            "_id": link["_id"],
            "locked": True,
            "lock_expires_at": {"$lt": now()},
        })
        if stale:
            await release_chat_lock(link["_id"], stale.get("lock_token", ""))
            lock_token = await claim_chat_lock(link["_id"])
        if not lock_token:
            await send_message(chat_id, "⏳ Still working on your previous question — try again in ~30s.")
            return
    await send_action(chat_id, "typing")
    try:
        text, attachment_ids, audio_media_id = await extract_question(
            message, workspace_id, link["user_id"], chat_id=chat_id
        )
        if not text and not attachment_ids and not audio_media_id:
            await send_message(
                chat_id,
                "⚠️ I can't process this message type yet. "
                "I understand: *text, photos, documents (PDF/DOCX/CSV/XLSX), and voice notes*. "
                "Try sending one of those!"
            )
            await release_chat_lock(link["_id"], lock_token)
            return
        if not text:
            text = "Explain this."
    except Exception as exc:
        await send_message(chat_id, "⚠️ Could not process that attachment — please try again.")
        await release_chat_lock(link["_id"], lock_token)
        return

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_typing_loop(chat_id, stop_typing))
    final_answer = ""
    investigation_id: str | None = None
    start_time = now()
    try:
        conversation_id = link.get("conversation_id")
        # 5-minute hard timeout prevents infinite hangs
        investigation_task = asyncio.create_task(_collect_investigation(
            workspace_id=workspace_id,
            user_id=link["user_id"],
            question=text,
            conversation_id=conversation_id,
            attachment_ids=attachment_ids,
            audio_media_id=audio_media_id,
        ))
        _RUNNING_TASKS[chat_id] = investigation_task
        try:
            result = await asyncio.wait_for(investigation_task, timeout=300)
            final_answer = result.get("answer", "")
            investigation_id = result.get("id")
            new_conversation = result.get("conversation_id")
            if new_conversation and new_conversation != conversation_id:
                db = get_db()
                await db.telegram_links.update_one(
                    {"_id": link["_id"]},
                    {"$set": {"last_investigation_id": investigation_id, "conversation_id": new_conversation}},
                )
            elif investigation_id:
                db = get_db()
                await db.telegram_links.update_one(
                    {"_id": link["_id"]},
                    {"$set": {"last_investigation_id": investigation_id}},
                )
        except asyncio.TimeoutError:
            investigation_task.cancel()
            final_answer = "⏰ That question is taking too long. Try a simpler question or /new to start fresh."
        except asyncio.CancelledError:
            # /stop or /clear cancelled this run — report it instead of hanging.
            final_answer = "⏹ Stopped. Send /new or ask again whenever you're ready."
        except Exception as exc:
            logger.error("investigation failed: %s", exc, exc_info=True)
            final_answer = "❌ Something went wrong. Please try again."
    finally:
        _RUNNING_TASKS.pop(chat_id, None)
        stop_typing.set()
        try:
            await asyncio.wait_for(typing_task, timeout=2.0)
        except (asyncio.TimeoutError, Exception):
            typing_task.cancel()
        await release_chat_lock(link["_id"], lock_token)
    elapsed = (now() - start_time).total_seconds()
    answer_text = clean_answer_for_telegram(final_answer or "Something went wrong. Please try again.")
    answer_text += maybe_add_image_hint(text, bool(attachment_ids or audio_media_id))
    if elapsed > 5:
        answer_text += f"\n\n_Solved in {elapsed:.1f}s_"
    await send_message(
        chat_id,
        answer_text,
        reply_markup=answer_keyboard(investigation_id),
    )


async def webhook_info() -> dict:
    result = await telegram_request("getWebhookInfo", {})
    return result.get("result", {})
