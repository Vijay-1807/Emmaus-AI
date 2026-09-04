from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.api.deps import get_current_user, require_workspace
from app.core.db import get_db
from app.core.config import get_settings
from app.models.schemas import DocumentOut
from app.services import document_service

router = APIRouter(prefix="/documents", tags=["documents"])


def to_out(document: dict) -> DocumentOut:
    return DocumentOut(
        id=document["_id"],
        workspace_id=document["workspace_id"],
        filename=document["filename"],
        source_type=document["source_type"],
        content_type=document.get("content_type", ""),
        status=document["status"],
        error=document.get("error"),
        num_chunks=document.get("num_chunks", 0),
        num_pages=document.get("num_pages", 0),
        media_url=(document.get("media") or {}).get("url"),
        size_bytes=document.get("size_bytes", 0),
        created_at=document["created_at"],
    )


@router.post("/upload", response_model=DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile,
    workspace_id: str,
    user: dict = Depends(get_current_user),
) -> DocumentOut:
    await require_workspace(workspace_id, user)
    chunks: list[bytes] = []
    total = 0
    settings = get_settings()
    while True:
        chunk = await file.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.max_upload_bytes:
            raise HTTPException(status_code=400, detail=f"file exceeds {settings.max_upload_mb}MB limit")
        chunks.append(chunk)
    data = b"".join(chunks)
    try:
        document = await document_service.create_document(
            workspace_id, user["_id"], file.filename or "upload", file.content_type or "", data
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return to_out(document)


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    workspace_id: str,
    user: dict = Depends(get_current_user),
) -> list[DocumentOut]:
    await require_workspace(workspace_id, user)
    return [to_out(d) for d in await document_service.list_documents(workspace_id)]


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: str,
    workspace_id: str,
    user: dict = Depends(get_current_user),
) -> DocumentOut:
    await require_workspace(workspace_id, user)
    document = await document_service.get_document(workspace_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document not found")
    return to_out(document)


@router.post("/copy", status_code=200)
async def copy_document(
    body: dict,
    user: dict = Depends(get_current_user),
) -> dict:
    """Copy a document (and its chunks) into another workspace for a new chat."""
    source_workspace_id = body.get("source_workspace_id")
    document_id = body.get("document_id")
    target_workspace_id = body.get("target_workspace_id")
    if not source_workspace_id or not document_id or not target_workspace_id:
        raise HTTPException(status_code=422, detail="source_workspace_id, document_id, and target_workspace_id are required")
    await require_workspace(source_workspace_id, user)
    await require_workspace(target_workspace_id, user)
    db = get_db()
    doc = await db.documents.find_one({"_id": document_id, "workspace_id": source_workspace_id})
    if not doc:
        raise HTTPException(status_code=404, detail="document not found in source workspace")
    from uuid import uuid4
    already = await db.documents.find_one({"workspace_id": target_workspace_id, "media.public_id": doc.get("media", {}).get("public_id")})
    if already:
        return {"document_id": already["_id"], "already_copied": True}
    import copy as _copy
    new_id = uuid4().hex
    new_doc = _copy.deepcopy(doc)
    new_doc["_id"] = new_id
    new_doc["workspace_id"] = target_workspace_id
    await db.documents.insert_one(new_doc)
    chunks = [c async for c in db.document_chunks.find({"document_id": document_id})]
    if chunks:
        for chunk in chunks:
            chunk["_id"] = uuid4().hex
            chunk["document_id"] = new_id
            chunk["workspace_id"] = target_workspace_id
        await db.document_chunks.insert_many(chunks)
    return {"document_id": new_id, "already_copied": False}


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    workspace_id: str,
    user: dict = Depends(get_current_user),
) -> None:
    await require_workspace(workspace_id, user)
    deleted = await document_service.delete_document(workspace_id, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="document not found")
