from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.api.deps import get_current_user, require_workspace
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
    data = await file.read()
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
