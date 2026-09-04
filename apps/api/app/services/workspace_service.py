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
    cursor = db.workspaces.find({"owner_id": owner_id}).sort("created_at", -1)
    workspaces = [w async for w in cursor]
    if not workspaces:
        return workspaces
    ws_ids = [w["_id"] for w in workspaces]
    doc_counts = {}
    ds_counts = {}
    inv_counts = {}
    doc_pipeline = [
        {"$match": {"workspace_id": {"$in": ws_ids}}},
        {"$group": {"_id": "$workspace_id", "count": {"$sum": 1}}},
    ]
    async for r in await db.documents.aggregate(doc_pipeline):
        doc_counts[r["_id"]] = r["count"]
    ds_pipeline = [
        {"$match": {"workspace_id": {"$in": ws_ids}}},
        {"$group": {"_id": "$workspace_id", "count": {"$sum": 1}}},
    ]
    async for r in await db.datasets.aggregate(ds_pipeline):
        ds_counts[r["_id"]] = r["count"]
    inv_pipeline = [
        {"$match": {"workspace_id": {"$in": ws_ids}, "status": "completed"}},
        {"$group": {"_id": "$workspace_id", "count": {"$sum": 1}}},
    ]
    async for r in await db.investigations.aggregate(inv_pipeline):
        inv_counts[r["_id"]] = r["count"]
    for w in workspaces:
        wid = w["_id"]
        w["document_count"] = doc_counts.get(wid, 0)
        w["dataset_count"] = ds_counts.get(wid, 0)
        w["investigation_count"] = inv_counts.get(wid, 0)
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


async def clear_workspace_data(workspace_id: str, owner_id: str) -> dict | None:
    db = get_db()
    workspace = await get_workspace(workspace_id, owner_id)
    if not workspace:
        return None

    chunks_res = await db.document_chunks.delete_many({"workspace_id": workspace_id})
    docs_res = await db.documents.delete_many({"workspace_id": workspace_id})
    datasets_res = await db.datasets.delete_many({"workspace_id": workspace_id})
    media_res = await db.media_assets.delete_many({"workspace_id": workspace_id})
    messages_res = await db.messages.delete_many({"workspace_id": workspace_id})
    convs_res = await db.conversations.delete_many({"workspace_id": workspace_id})
    invs_res = await db.investigations.delete_many({"workspace_id": workspace_id})

    return {
        "workspace_id": workspace_id,
        "document_chunks_deleted": chunks_res.deleted_count,
        "documents_deleted": docs_res.deleted_count,
        "datasets_deleted": datasets_res.deleted_count,
        "media_assets_deleted": media_res.deleted_count,
        "messages_deleted": messages_res.deleted_count,
        "conversations_deleted": convs_res.deleted_count,
        "investigations_deleted": invs_res.deleted_count,
    }


async def get_workspace_storage_summary(workspace_id: str, owner_id: str) -> dict | None:
    db = get_db()
    workspace = await get_workspace(workspace_id, owner_id)
    if not workspace:
        return None

    docs_cursor = db.documents.find({"workspace_id": workspace_id}, {"size_bytes": 1})
    doc_count = 0
    doc_bytes = 0
    async for d in docs_cursor:
        doc_count += 1
        doc_bytes += d.get("size_bytes", 0)

    ds_cursor = db.datasets.find({"workspace_id": workspace_id}, {"size_bytes": 1, "row_count": 1})
    ds_count = 0
    ds_bytes = 0
    ds_rows = 0
    async for ds in ds_cursor:
        ds_count += 1
        ds_bytes += ds.get("size_bytes", 0)
        ds_rows += ds.get("row_count", 0)

    media_count = await db.media_assets.count_documents({"workspace_id": workspace_id})
    msg_count = await db.messages.count_documents({"workspace_id": workspace_id})
    conv_count = await db.conversations.count_documents({"workspace_id": workspace_id})

    return {
        "workspace_id": workspace_id,
        "documents": {"count": doc_count, "size_bytes": doc_bytes},
        "datasets": {"count": ds_count, "size_bytes": ds_bytes, "row_count": ds_rows},
        "media": {"count": media_count},
        "chat": {"conversations": conv_count, "messages": msg_count},
        "total_size_bytes": doc_bytes + ds_bytes,
    }
