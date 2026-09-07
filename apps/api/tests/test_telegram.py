"""Telegram bot unit tests (Bot API calls mocked, mongomock DB)."""

import pytest

import app.integrations.telegram as tg


@pytest.fixture
def tg_outbox(monkeypatch):
    sent: list[dict] = []

    async def fake_request(method: str, payload: dict) -> dict:
        sent.append({"method": method, "payload": payload})
        return {"ok": True, "result": {}}

    monkeypatch.setattr(tg, "telegram_request", fake_request)
    return sent


def make_message(text: str, chat_id: int = 777):
    return {
        "message": {
            "chat": {"id": chat_id},
            "from": {"first_name": "Tester"},
            "text": text,
        }
    }


@pytest.mark.asyncio
async def test_start_welcomes_and_links(tg_outbox):
    await tg.handle_update(make_message("/start"))
    assert tg_outbox, "expected a welcome message"
    assert tg_outbox[0]["method"] == "sendMessage"
    assert "Welcome to Emmaus AI" in tg_outbox[0]["payload"]["text"]


@pytest.mark.asyncio
async def test_help_lists_commands(tg_outbox):
    await tg.handle_update(make_message("/help"))
    text = tg_outbox[-1]["payload"]["text"]
    assert "/new" in text and "/history" in text and "/status" in text


@pytest.mark.asyncio
async def test_unknown_command_guided(tg_outbox):
    await tg.handle_update(make_message("/frobnicate"))
    assert "Unknown command" in tg_outbox[-1]["payload"]["text"]


@pytest.mark.asyncio
async def test_new_resets_conversation(tg_outbox):
    import app.core.db as db_module

    await tg.handle_update(make_message("/start", chat_id=888))
    link = await db_module._db.telegram_links.find_one({"telegram_chat_id": 888})
    await db_module._db.telegram_links.update_one(
        {"_id": link["_id"]}, {"$set": {"conversation_id": "conv-1"}}
    )
    await tg.handle_update(make_message("/new", chat_id=888))
    link = await db_module._db.telegram_links.find_one({"telegram_chat_id": 888})
    assert link["conversation_id"] is None
    assert "Fresh chat" in tg_outbox[-1]["payload"]["text"]


@pytest.mark.asyncio
async def test_rate_limit_blocks_burst(tg_outbox):
    import time

    import app.core.db as db_module

    await tg.handle_update(make_message("/start", chat_id=999))
    link = await db_module._db.telegram_links.find_one({"telegram_chat_id": 999})
    # Simulate 8 messages inside the window.
    await db_module._db.telegram_links.update_one(
        {"_id": link["_id"]},
        {"$set": {"msg_times": [time.time()] * 8, "locked": False}},
    )
    link = await db_module._db.telegram_links.find_one({"telegram_chat_id": 999})
    verdict = await tg.check_rate_limit(link)
    assert verdict is not None and "Slow down" in verdict


@pytest.mark.asyncio
async def test_busy_lock_blocks_overlap(tg_outbox):
    import app.core.db as db_module

    await tg.handle_update(make_message("/start", chat_id=1001))
    link = await db_module._db.telegram_links.find_one({"telegram_chat_id": 1001})
    await db_module._db.telegram_links.update_one(
        {"_id": link["_id"]}, {"$set": {"locked": True}}
    )
    link = await db_module._db.telegram_links.find_one({"telegram_chat_id": 1001})
    verdict = await tg.check_rate_limit(link)
    assert verdict is not None and "still working" in verdict


@pytest.mark.asyncio
async def test_sources_callback_formats_citations(tg_outbox):
    import app.core.db as db_module
    from datetime import datetime, timezone

    await tg.handle_update(make_message("/start", chat_id=1002))
    link = await db_module._db.telegram_links.find_one({"telegram_chat_id": 1002})
    await db_module._db.investigations.insert_one(
        {
            "_id": "inv-tg-1",
            "workspace_id": link["workspace_id"],
            "question": "q",
            "answer": "a",
            "citations": [
                {"document_name": "report.pdf", "page": 3},
                {"document_name": "notes.txt", "page": None},
            ],
            "created_at": datetime.now(timezone.utc),
        }
    )
    await tg.handle_update(
        {
            "callback_query": {
                "id": "cq-1",
                "data": "sources:inv-tg-1",
                "message": {"chat": {"id": 1002}},
            }
        }
    )
    texts = [m["payload"].get("text", "") for m in tg_outbox if m["method"] == "sendMessage"]
    assert any("report.pdf" in t and "notes.txt" in t for t in texts)


@pytest.mark.asyncio
async def test_newchat_callback_resets(tg_outbox):
    import app.core.db as db_module

    await tg.handle_update(make_message("/start", chat_id=1003))
    link = await db_module._db.telegram_links.find_one({"telegram_chat_id": 1003})
    await db_module._db.telegram_links.update_one(
        {"_id": link["_id"]}, {"$set": {"conversation_id": "conv-9"}}
    )
    await tg.handle_update(
        {
            "callback_query": {
                "id": "cq-2",
                "data": "newchat",
                "message": {"chat": {"id": 1003}},
            }
        }
    )
    link = await db_module._db.telegram_links.find_one({"telegram_chat_id": 1003})
    assert link["conversation_id"] is None


@pytest.mark.asyncio
async def test_answer_keyboard_shape():
    kb = tg.answer_keyboard("inv-1")
    assert kb["inline_keyboard"][0][0]["callback_data"] == "sources:inv-1"
    kb2 = tg.answer_keyboard(None)
    assert all(b["callback_data"] == "newchat" for b in kb2["inline_keyboard"][0])


@pytest.mark.asyncio
async def test_stale_lock_expires(tg_outbox):
    """A lock from a crashed run must not brick the chat forever."""
    import app.core.db as db_module
    from datetime import datetime, timedelta, timezone

    await tg.handle_update(make_message("/start", chat_id=1005))
    link = await db_module._db.telegram_links.find_one({"telegram_chat_id": 1005})
    await db_module._db.telegram_links.update_one(
        {"_id": link["_id"]},
        {
            "$set": {
                "locked": True,
                "lock_token": "dead-token",
                "lock_expires_at": datetime.now(timezone.utc) - timedelta(seconds=10),
            }
        },
    )
    link = await db_module._db.telegram_links.find_one({"telegram_chat_id": 1005})
    verdict = await tg.check_rate_limit(link)
    assert verdict is None
    link = await db_module._db.telegram_links.find_one({"telegram_chat_id": 1005})
    assert link["locked"] is False


@pytest.mark.asyncio
async def test_update_claim_is_idempotent():
    import app.core.db as db_module

    await db_module._db.telegram_updates.create_index("update_id", unique=True)
    assert await tg.claim_update(123456) is True
    assert await tg.claim_update(123456) is False


def test_clean_answer_for_telegram_strips_model_artifacts():
    raw = (
        "- **Aurora:** It processes **12\u202fmillion lookups/s**【1†L1-L2】.\n"
        "- Beacon refreshes **every 90\u202fseconds**【2†L3】.\n\n"
        "Confidence: high - the handbook explicitly provides both figures."
    )
    cleaned = tg.clean_answer_for_telegram(raw)
    assert "【" not in cleaned and "†" not in cleaned
    assert "12 million" in cleaned and "90 seconds" in cleaned
    assert "Confidence" not in cleaned
    assert "\u202f" not in cleaned


def test_clean_answer_for_telegram_preserves_plain_text():
    assert tg.clean_answer_for_telegram("Hello! How can I assist?") == "Hello! How can I assist?"


def _mock_voice_stack(monkeypatch):
    """Voice download + storage + transcription without network or disk."""

    async def fake_download(file_id: str):
        return (b"fake-ogg-bytes", "voice_note.ogg")

    async def fake_transcribe(data: bytes, filename: str):
        return {"text": "what is in this picture"}

    class FakeMediaService:
        async def upload(self, data, filename, workspace_id, kind):
            from types import SimpleNamespace

            return SimpleNamespace(
                url=f"/media/{filename}",
                public_id=f"ws/{filename}",
                mode="local",
                bytes_path=f"media/{filename}",
            )

    monkeypatch.setattr(tg, "download_file", fake_download)
    monkeypatch.setattr("app.audio.transcriber.transcribe_audio", fake_transcribe)
    monkeypatch.setattr(
        "app.services.media_service.MediaService", FakeMediaService
    )


def make_voice(chat_id: int = 777):
    return {
        "message": {
            "chat": {"id": chat_id},
            "from": {"first_name": "Vijay"},
            "voice": {"file_id": "voice-file-1"},
        }
    }


@pytest.mark.asyncio
async def test_voice_without_caption_parks_and_asks(tg_outbox, monkeypatch):
    import app.core.db as db_module

    _mock_voice_stack(monkeypatch)

    async def explode(**kwargs):
        raise AssertionError("investigation must not run before the ask")
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(tg, "run_investigation", explode)
    await tg.handle_update(make_voice(chat_id=2001))

    texts = [
        m["payload"].get("text", "")
        for m in tg_outbox
        if m["method"] == "sendMessage"
    ]
    assert any("Voice note received, Vijay" in t for t in texts)
    assert any("what is in this picture" in t for t in texts)
    assert any("What should I investigate" in t for t in texts)

    link = await db_module._db.telegram_links.find_one({"telegram_chat_id": 2001})
    assert link and link.get("pending_audio_id")


@pytest.mark.asyncio
async def test_followup_text_consumes_parked_audio(tg_outbox, monkeypatch):
    import app.core.db as db_module

    _mock_voice_stack(monkeypatch)
    captured: dict = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        yield {
            "type": "done",
            "investigation": {
                "answer": "The picture shows a cat.",
                "id": "inv-voice-1",
                "conversation_id": "conv-voice-1",
            },
        }

    monkeypatch.setattr(tg, "run_investigation", fake_run)
    await tg.handle_update(make_voice(chat_id=2002))
    link = await db_module._db.telegram_links.find_one({"telegram_chat_id": 2002})
    parked = link["pending_audio_id"]

    await tg.handle_update(make_message("is it a cat", chat_id=2002))

    assert captured.get("audio_media_id") == parked
    link = await db_module._db.telegram_links.find_one({"telegram_chat_id": 2002})
    assert not link.get("pending_audio_id")
    texts = [
        m["payload"].get("text", "")
        for m in tg_outbox
        if m["method"] == "sendMessage"
    ]
    assert any("picture shows a cat" in t for t in texts)
