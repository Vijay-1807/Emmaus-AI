import uuid
from datetime import datetime, timezone

from app.core.db import get_db


def now() -> datetime:
    return datetime.now(timezone.utc)


async def create_workspace(owner_id: str, name: str, description: str) -> dict:
    db = get_db()
    workspace = {
        "_id": uuid.uuid4().hex,
        "name": name.strip(),
        "description": (description or "").strip(),
        "owner_id": owner_id,
        "created_at": now(),
    }
    await db.workspaces.insert_one(workspace)
    return workspace


async def list_workspaces(owner_id: str) -> list[dict]:
    db = get_db()
    workspaces = []
    cursor = db.workspaces.find({"owner_id": owner_id}).sort("created_at", -1)
    async for workspace in cursor:
        workspace_id = workspace["_id"]
        workspace["document_count"] = await db.documents.count_documents(
            {"workspace_id": workspace_id}
        )
        workspace["dataset_count"] = await db.datasets.count_documents(
            {"workspace_id": workspace_id}
        )
        workspace["investigation_count"] = await db.investigations.count_documents(
            {"workspace_id": workspace_id, "status": "completed"}
        )
        workspaces.append(workspace)
    return workspaces


async def get_workspace(workspace_id: str, owner_id: str) -> dict | None:
    db = get_db()
    return await db.workspaces.find_one({"_id": workspace_id, "owner_id": owner_id})


async def update_workspace(workspace_id: str, owner_id: str, updates: dict) -> dict | None:
    db = get_db()
    clean = {k: v for k, v in updates.items() if v is not None and k in ("name", "description")}
    if not clean:
        return await get_workspace(workspace_id, owner_id)
    await db.workspaces.update_one({"_id": workspace_id, "owner_id": owner_id}, {"$set": clean})
    return await get_workspace(workspace_id, owner_id)


async def delete_workspace(workspace_id: str, owner_id: str) -> bool:
    db = get_db()
    workspace = await get_workspace(workspace_id, owner_id)
    if not workspace:
        return False
    await db.document_chunks.delete_many({"workspace_id": workspace_id})
    await db.documents.delete_many({"workspace_id": workspace_id})
    await db.datasets.delete_many({"workspace_id": workspace_id})
    await db.media_assets.delete_many({"workspace_id": workspace_id})
    await db.messages.delete_many({"workspace_id": workspace_id})
    await db.conversations.delete_many({"workspace_id": workspace_id})
    await db.investigations.delete_many({"workspace_id": workspace_id})
    await db.workspaces.delete_one({"_id": workspace_id})
    return True
