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


# Strong: explicit creation verb + image noun ("draw me a cat" with a noun),
# bare draw/paint/imagine + object ("paint a mountain", "imagine a city"),
# or a bare image noun phrase ("photos of beaches please", "…moon image").
_STRONG_IMAGE_RE = re.compile(
    r"\b(generate|create|make|draw|paint|design)\b"
    r".{0,40}\b(images?|pictures?|photos?|paintings?|drawings?|artworks?|wallpapers?|logos?|posters?|art)\b"
    r"|\b(draw|paint|imagine)\b\s+(me\s+)?(a|an|the|some|my)\b"
    r"|\b(images?|pictures?|photos?)\b.{0,20}\b(of|for|please)\b"
    r"|\b(images?|pictures?)\b[.!?,]*$",
    re.IGNORECASE,
)

# Question words - if present, it's a question about sources, not an image wish.
_QUESTION_RE = re.compile(
    r"\?|\b(who|what|when|where|why|how|which|whom|whose|is|are|was|were|do|does|did|"
    r"can|could|should|explain|summar\w*|analyz\w*|tell|describe|list|show|find|compare)\b",
    re.IGNORECASE,
)


def classify_image_request(question: str, has_attachments: bool) -> str:
    """Classify plain-text input for image intent.

    Returns "strong" (generate directly), "weak" (investigate + hint),
    or "none". Attachments always win - e.g. "generate alt text" with a
    photo attached must go to vision, never to image generation.
    """
    if has_attachments:
        return "none"
    q = (question or "").strip()
    if not q:
        return "none"
    if _STRONG_IMAGE_RE.search(q):
        return "strong"
    if len(q.split()) > 3 and not _QUESTION_RE.search(q):
        return "weak"
    return "none"


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
    "📎 *Tips:* Attach a file with a caption, use /generate <prompt> for AI images, "
    "or just describe one (\"draw me a cat\") and I'll create it.\n\n"
    "Commands: /new  /stop  /clear  /history  /status  /generate  /help\n\n"
    "Built by @vijay_1807"
)

HELP_TEXT = (
    "📖 *Emmaus AI - Help*\n\n"
    "*Ask:*\n"
    "• Type any question about your sources.\n"
    "• Attach a doc (PDF/DOCX/TXT/MD), dataset (CSV/XLSX/XLS), photo, or voice note - with or without a caption.\n\n"
    "*Commands:*\n"
    "• /new - fresh chat (clears conversation memory)\n"
    "• /stop - cancel a running investigation\n"
    "• /clear - wipe all workspace data (docs, datasets, history)\n"
    "• /history - last 5 investigations\n"
    "• /status - your docs / datasets / media / chats\n"
    "• /generate <prompt> - generate an image with AI\n"
    "• /help - this help\n\n"
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
                stage = update.get("_stage", "start")
                await send_message(
                    chat_id,
                    f"Something went wrong ({stage}: {type(exc).__name__}). "
                    "Please try again - if it repeats, send /stop then /new.",
                )
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
            # Markdown failed - try HTML fallback, then plain text.
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
                # HTML also failed - send plain text, still keep buttons
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
    """Bottom reply-keyboard so commands are always one tap away (not a slash).

    One-time: it collapses after each tap so it never covers the chat.
    The bot Menu (registered commands) reopens it anytime.
    """
    return {
        "keyboard": [
            [{"text": "/status"}, {"text": "/history"}, {"text": "/new"}, {"text": "/clear"}],
            [{"text": "/generate"}, {"text": "/stop"}, {"text": "/help"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True,
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
                # Stale lock from a crashed run - clear it atomically
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
                    return "⏳ I'm still working on your previous question - one moment…"
            else:
                return "⏳ I'm still working on your previous question - one moment…"
        else:
            return "⏳ I'm still working on your previous question - one moment…"
    
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
            return f"🐢 Slow down - too many messages at once, try again in ~{wait}s."
    
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
        link["_is_new"] = True
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
        # Voice with no caption leaves text empty on purpose: the caller
        # parks the audio and asks what to investigate (transcript stays
        # on the media record for the ack message).

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
                await send_message(chat_id, "⚠️ Image analysis partially failed - I'll do my best with the text question.")
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


async def _generate_and_send_image(chat_id: int, prompt: str) -> None:
    """Run FLUX.1 generation and deliver the photo. All errors are user-facing."""
    await send_action(chat_id, "upload_photo")
    try:
        from app.services.image_service import get_image_service
        import base64

        service = get_image_service()
        result = await service.generate(prompt=prompt)

        if not result.success:
            await send_message(chat_id, f"❌ Image generation failed: {result.error}")
            return

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
        await send_message(chat_id, "❌ Image generation failed - please try again or use a different prompt.")


async def handle_command(chat_id: int, link: dict, command: str, display_name: str = "") -> bool:
    """Returns True if the text was a command (handled, skip investigation)."""
    db = get_db()
    workspace_id = link["workspace_id"]
    cmd = command.split()[0].split("@")[0]

    if cmd == "/start":
        safe_name = re.sub(r"([*_`\[\]])", r"\\\1", (display_name or "").strip()[:30])
        greeting = f"Welcome to Emmaus AI{', ' + safe_name if safe_name else ''}!"
        text = WELCOME_TEXT.replace("Welcome to Emmaus AI", greeting, 1)
        if link.get("_is_new"):
            text += "\n\n_First visit can take ~30s while the servers wake up - just ask and stay here._"
        await send_message(
            chat_id,
            text,
            reply_markup=persistent_keyboard(),
        )
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
                reply_markup=persistent_keyboard(),
            )
            return True
        
        # Check if Cloudflare is configured
        settings = get_settings()
        if not settings.has_cloudflare:
            await send_message(
                chat_id,
                "❌ Image generation is not configured. "
                "Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN to enable this feature.",
            )
            return True

        await _generate_and_send_image(chat_id, prompt)
        return True
    if cmd == "/help":
        await send_message(chat_id, HELP_TEXT, reply_markup=persistent_keyboard())
        return True
    if cmd == "/new":
        if _is_locked(link):
            await send_message(chat_id, "⏳ Still working on your previous question - send /stop to cancel it, or try /new in a moment.")
            return True
        await db.telegram_links.update_one(
            {"_id": link["_id"]},
            {"$set": {"conversation_id": None, "last_investigation_id": None}, "$unset": {"pending_audio_id": ""}},
        )
        await send_message(chat_id, "💬 Fresh chat started - previous context cleared.",
            reply_markup=persistent_keyboard())
        return True
    if cmd == "/stop":
        cancelled = await _cancel_running(chat_id)
        await _force_unlock(link["_id"])
        await send_message(
            chat_id,
            "⏹ Stopped the running investigation." if cancelled else "Nothing running - ask me anything!",
            reply_markup=persistent_keyboard(),
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
            {"$set": {"conversation_id": None, "last_investigation_id": None}, "$unset": {"pending_audio_id": ""}},
        )
        total = docs.deleted_count + datasets.deleted_count + media.deleted_count + convs.deleted_count + invs.deleted_count
        await send_message(
            chat_id,
            f"🗑️ *Workspace cleared*\n\n"
            f"Deleted: {docs.deleted_count} docs, {datasets.deleted_count} datasets, "
            f"{media.deleted_count} media, {convs.deleted_count} conversations, "
            f"{invs.deleted_count} investigations.\n\n"
            f"Start fresh - upload a file or ask a question!",
            reply_markup=persistent_keyboard(),
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
            + ("\n".join(lines) if lines else "Nothing yet - ask me anything!")
            + ("\n\n💬 Ask again to revisit any topic. Use /clear to wipe history." if lines else ""),
            reply_markup=persistent_keyboard(),
        )
        return True
    if cmd == "/status":
        docs = await db.documents.count_documents({"workspace_id": workspace_id})
        datasets = await db.datasets.count_documents({"workspace_id": workspace_id})
        media = await db.media_assets.count_documents({"workspace_id": workspace_id})
        convs = await db.conversations.count_documents({"workspace_id": workspace_id})
        try:
            # Sum in Python: AsyncCollection.aggregate needs awaiting in this
            # stack and behaves differently under test doubles - a find loop
            # works identically everywhere.
            total_bytes = 0
            cursor = db.media_assets.find(
                {"workspace_id": workspace_id}, {"size_bytes": 1}
            )
            async for m in cursor:
                try:
                    total_bytes += int(m.get("size_bytes") or 0)
                except (TypeError, ValueError):
                    pass
        except Exception:
            total_bytes = 0
        size_str = (
            f"{total_bytes / 1048576:.1f} MB"
            if total_bytes >= 1048576
            else f"{total_bytes / 1024:.0f} KB" if total_bytes >= 1024
            else f"{total_bytes} B"
        )
        await send_message(
            chat_id,
            f"📊 *Your workspace*\n\nDocuments: {docs}\nDatasets: {datasets}\n"
            f"Media: {media} ({size_str})\nConversations: {convs}",
            reply_markup=persistent_keyboard(),
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
            await send_message(chat_id, "⏳ Still working on your previous question - send /stop to cancel it.")
            return
        await db.telegram_links.update_one(
            {"_id": link["_id"]},
            {"$set": {"conversation_id": None, "last_investigation_id": None}, "$unset": {"pending_audio_id": ""}},
        )
        await send_message(chat_id, "💬 Fresh chat started - previous context cleared.")
    elif data.startswith("sources:"):
        inv_id = data.split(":", 1)[1]
        inv = await db.investigations.find_one(
            {"_id": inv_id, "workspace_id": link["workspace_id"]}
        )
        await send_message(
            chat_id, format_citations(inv) if inv else "Sources expired - ask again to refresh."
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
    update["_stage"] = "link"
    link = await get_or_create_link(chat_id, message.get("from", {}))
    workspace_id = link["workspace_id"]
    update["_stage"] = "command"

    text = (message.get("text") or "").strip()
    if text.startswith("/"):
        display_name = (message.get("from") or {}).get("first_name", "")
        if await handle_command(chat_id, link, text, display_name=display_name):
            return
        await send_message(chat_id, "Unknown command - I know /new, /stop, /clear, /history, /status, /generate and /help.",
            reply_markup=persistent_keyboard())
        return

    update["_stage"] = "rate"
    limited = await check_rate_limit(link)
    if limited:
        await send_message(chat_id, limited)
        return

    update["_stage"] = "extract"
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
            return
        if not text:
            text = "Explain this."
    except Exception:
        await send_message(chat_id, "Attachment failed - please try again.")
        return

    db = get_db()
    voice_no_caption = bool(message.get("voice") or message.get("audio")) and not (
        message.get("text") or message.get("caption") or ""
    ).strip()
    if audio_media_id and voice_no_caption and not attachment_ids:
        # Voice note with no caption: park it and ask what to investigate
        # instead of guessing. The next text message picks it up.
        media = await db.media_assets.find_one({"_id": audio_media_id})
        transcript = ((media or {}).get("transcript") or "").strip()
        await db.telegram_links.update_one(
            {"_id": link["_id"]}, {"$set": {"pending_audio_id": audio_media_id}}
        )
        raw_name = ((message.get("from") or {}).get("first_name") or "").strip()[:30]
        safe_name = re.sub(r"([*_`\[\]])", r"\\\1", raw_name)
        greeting = f"Voice note received, {safe_name}" if safe_name else "Voice note received"
        preview = f' - you said: "{transcript[:200]}"' if transcript else ""
        await send_message(
            chat_id,
            f"{greeting}{preview}.\n\nWhat should I investigate in it? Reply with your question.",
        )
        return

    # A parked voice note is consumed by the next plain-text question.
    # Fresh attachments supersede it.
    pending_audio = link.get("pending_audio_id")
    if pending_audio and not audio_media_id and not attachment_ids:
        parked = await db.media_assets.find_one(
            {"_id": pending_audio, "workspace_id": workspace_id}
        )
        if parked:
            audio_media_id = pending_audio
    await db.telegram_links.update_one(
        {"_id": link["_id"]}, {"$unset": {"pending_audio_id": ""}}
    )

    # Image-intent routing BEFORE the RAG lock: strong wishes generate
    # directly (seconds), weak ones investigate with a /generate hint.
    image_mode = classify_image_request(text, bool(attachment_ids or audio_media_id))
    if image_mode == "strong" and get_settings().has_cloudflare:
        # Hold the single-flight lock if free so indicators don't interleave,
        # but never block image requests on a slow RAG run.
        gen_token = await claim_chat_lock(link["_id"])
        try:
            await _generate_and_send_image(chat_id, text)
        finally:
            if gen_token:
                await release_chat_lock(link["_id"], gen_token)
        return

    update["_stage"] = "lock"
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
            try:
                await release_chat_lock(link["_id"], stale.get("lock_token", ""))
                lock_token = await claim_chat_lock(link["_id"])
            except Exception:
                logger.warning("stale lock clear failed", exc_info=True)
        if not lock_token:
            await send_message(chat_id, "⏳ Still working on your previous question - send /stop to cancel it, or try again in ~30s.")
            return

    update["_stage"] = "investigate"
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
            # /stop or /clear cancelled this run - report it instead of hanging.
            final_answer = "⏹ Stopped. Send /new or ask again whenever you're ready."
        except Exception as exc:
            logger.error("investigation failed: %s", exc, exc_info=True)
            final_answer = "❌ Something went wrong. Please try again."
    finally:
        update["_stage"] = "cleanup"
        _RUNNING_TASKS.pop(chat_id, None)
        stop_typing.set()
        try:
            await asyncio.wait_for(typing_task, timeout=2.0)
        except (asyncio.TimeoutError, Exception):
            typing_task.cancel()
        try:
            await release_chat_lock(link["_id"], lock_token)
        except Exception:
            logger.warning("lock release failed", exc_info=True)
    elapsed = (now() - start_time).total_seconds()
    answer_text = clean_answer_for_telegram(final_answer or "Something went wrong. Please try again.")
    if image_mode == "weak":
        answer_text += "\n\n🎨 _If you wanted this as an image, use /generate <prompt>_"
    if image_mode == "strong":
        # Cloudflare wasn't configured so this ran as a normal investigation.
        answer_text += "\n\n🎨 _Tip: set up image generation to create pictures directly with /generate <prompt>_"
    if elapsed > 5:
        answer_text += f"\n\n_Solved in {elapsed:.1f}s_"
    update["_stage"] = "reply"
    try:
        await send_message(
            chat_id,
            answer_text,
            reply_markup=answer_keyboard(investigation_id),
        )
    except Exception:
        logger.error("telegram answer delivery failed", exc_info=True)
        try:
            await telegram_request("sendMessage", {"chat_id": chat_id, "text": answer_text[:4000]})
        except Exception:
            pass


async def webhook_info() -> dict:
    result = await telegram_request("getWebhookInfo", {})
    return result.get("result", {})
