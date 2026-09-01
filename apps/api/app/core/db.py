import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings

logger = logging.getLogger("vedax.db")

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None

MONGO_INDEXES: dict[str, list[dict]] = {
    "users": [{"name": "email_unique", "key": [("email", 1)], "unique": True}],
    "refresh_tokens": [
        {"name": "user_idx", "key": [("user_id", 1)]},
        {"name": "jti_unique", "key": [("jti", 1)], "unique": True},
    ],
    "workspaces": [
        {"name": "owner_idx", "key": [("owner_id", 1), ("created_at", -1)]},
    ],
    "documents": [
        {"name": "workspace_idx", "key": [("workspace_id", 1), ("created_at", -1)]},
    ],
    "document_chunks": [
        {"name": "doc_idx", "key": [("document_id", 1)]},
        {"name": "workspace_idx", "key": [("workspace_id", 1)]},
    ],
    "datasets": [
        {"name": "workspace_idx", "key": [("workspace_id", 1), ("created_at", -1)]},
    ],
    "media_assets": [
        {"name": "workspace_idx", "key": [("workspace_id", 1), ("created_at", -1)]},
    ],
    "conversations": [
        {"name": "workspace_idx", "key": [("workspace_id", 1), ("updated_at", -1)]},
    ],
    "messages": [
        {"name": "conversation_idx", "key": [("conversation_id", 1), ("created_at", 1)]},
    ],
    "investigations": [
        {"name": "workspace_idx", "key": [("workspace_id", 1), ("created_at", -1)]},
    ],
    "model_runs": [
        {"name": "investigation_idx", "key": [("investigation_id", 1)]},
        {"name": "created_idx", "key": [("created_at", -1)]},
    ],
    "tool_runs": [
        {"name": "investigation_idx", "key": [("investigation_id", 1)]},
    ],
    "evaluation_runs": [
        {"name": "created_idx", "key": [("created_at", -1)]},
    ],
    "telegram_links": [
        {"name": "chat_unique", "key": [("telegram_chat_id", 1)], "unique": True},
    ],
}


async def connect_db() -> None:
    global _client, _db
    settings = get_settings()
    _client = AsyncIOMotorClient(settings.mongodb_uri, serverSelectionTimeoutMS=8000)
    _db = _client[settings.mongodb_db]
    await _client.admin.command("ping")
    await _ensure_indexes()
    logger.info("connected", extra={"event": "db_connected"})


async def _ensure_indexes() -> None:
    for collection, indexes in MONGO_INDEXES.items():
        col = _db[collection]
        existing = {info["name"] async for info in col.list_indexes()}
        for spec in indexes:
            if spec["name"] not in existing:
                options = {"name": spec["name"]}
                if spec.get("unique"):
                    options["unique"] = True
                await col.create_index(spec["key"], **options)


async def close_db() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("database not initialized")
    return _db


@asynccontextmanager
async def lifespan_db() -> AsyncIterator[None]:
    await connect_db()
    try:
        yield
    finally:
        await close_db()
