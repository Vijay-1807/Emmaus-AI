from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import get_current_user, require_workspace
from app.models.schemas import DatasetOut
from app.services import dataset_service

router = APIRouter(prefix="/datasets", tags=["datasets"])

# Safety limits
MAX_CHUNKS_PER_COPY = 10000
MAX_ROWS_PER_COPY = 100000


class CopyDatasetRequest(BaseModel):
    source_workspace_id: str = Field(..., min_length=1, max_length=100)
    dataset_id: str = Field(..., min_length=1, max_length=100)
    target_workspace_id: str = Field(..., min_length=1, max_length=100)


def to_out(dataset: dict) -> DatasetOut:
    return DatasetOut(
        id=dataset["_id"],
        workspace_id=dataset["workspace_id"],
        filename=dataset["filename"],
        status=dataset["status"],
        error=dataset.get("error"),
        num_rows=dataset.get("num_rows", 0),
        num_columns=dataset.get("num_columns", 0),
        columns=dataset.get("columns", []),
        sample_rows=dataset.get("sample_rows", []),
        size_bytes=dataset.get("size_bytes", 0),
        created_at=dataset["created_at"],
    )


@router.post("/upload", response_model=DatasetOut, status_code=201)
async def upload_dataset(
    file: UploadFile,
    workspace_id: str,
    user: dict = Depends(get_current_user),
) -> DatasetOut:
    await require_workspace(workspace_id, user)
    data = await file.read()
    try:
        dataset = await dataset_service.create_dataset(
            workspace_id, user["_id"], file.filename or "dataset.csv", file.content_type or "", data
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return to_out(dataset)


@router.get("", response_model=list[DatasetOut])
async def list_datasets(
    workspace_id: str, user: dict = Depends(get_current_user)
) -> list[DatasetOut]:
    await require_workspace(workspace_id, user)
    return [to_out(d) for d in await dataset_service.list_datasets(workspace_id)]


@router.get("/{dataset_id}", response_model=DatasetOut)
async def get_dataset(
    dataset_id: str, workspace_id: str, user: dict = Depends(get_current_user)
) -> DatasetOut:
    await require_workspace(workspace_id, user)
    dataset = await dataset_service.get_dataset(workspace_id, dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="dataset not found")
    return to_out(dataset)


@router.post("/copy", status_code=200)
async def copy_dataset(
    body: CopyDatasetRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """Copy a dataset from one workspace to another with safety limits."""
    from uuid import uuid4
    from app.core.db import get_db
    from datetime import datetime, timezone

    db = get_db()
    
    # Verify workspaces exist and user has access
    await require_workspace(body.source_workspace_id, user)
    await require_workspace(body.target_workspace_id, user)
    
    # Check for self-copy
    if body.source_workspace_id == body.target_workspace_id:
        raise HTTPException(status_code=400, detail="Cannot copy dataset to the same workspace")
    
    # Get source dataset
    ds = await db.datasets.find_one({"_id": body.dataset_id, "workspace_id": body.source_workspace_id})
    if not ds:
        raise HTTPException(status_code=404, detail="dataset not found in source workspace")
    
    # Check for duplicate (same media file)
    already = await db.datasets.find_one({
        "workspace_id": body.target_workspace_id,
        "media.public_id": ds.get("media", {}).get("public_id")
    })
    if already:
        return {"dataset_id": already["_id"], "already_copied": True}
    
    # Check row count limit
    num_rows = ds.get("num_rows", 0)
    if num_rows > MAX_ROWS_PER_COPY:
        raise HTTPException(
            status_code=400,
            detail=f"Dataset has {num_rows} rows, exceeding limit of {MAX_ROWS_PER_COPY}"
        )
    
    # Count chunks before copying
    chunk_count = await db.document_chunks.count_documents({"document_id": body.dataset_id})
    if chunk_count > MAX_CHUNKS_PER_COPY:
        raise HTTPException(
            status_code=400,
            detail=f"Dataset has {chunk_count} chunks, exceeding limit of {MAX_CHUNKS_PER_COPY}"
        )
    
    # Deep copy and update metadata (not embeddings - keep separate)
    new_id = uuid4().hex
    new_ds = ds.copy()  # Shallow copy is sufficient for top-level
    new_ds["_id"] = new_id
    new_ds["workspace_id"] = body.target_workspace_id
    new_ds["created_at"] = datetime.now(timezone.utc)
    
    # Remove embedding vectors to prevent cross-workspace data leakage
    # Embeddings are tied to the source workspace's vector index
    new_ds.pop("embedding", None)
    
    # Insert dataset record
    await db.datasets.insert_one(new_ds)
    
    # Copy chunks in batches to avoid memory issues
    batch_size = 1000
    chunks_copied = 0
    async for chunk in db.document_chunks.find({"document_id": body.dataset_id}):
        chunk["_id"] = uuid4().hex
        chunk["document_id"] = new_id
        chunk["workspace_id"] = body.target_workspace_id
        # Remove embedding vector from chunk to prevent cross-workspace leakage
        chunk.pop("embedding", None)
        
        await db.document_chunks.insert_one(chunk)
        chunks_copied += 1
        
        if chunks_copied >= MAX_CHUNKS_PER_COPY:
            break
    
    return {
        "dataset_id": new_id,
        "already_copied": False,
        "rows_copied": num_rows,
        "chunks_copied": chunks_copied
    }


@router.delete("/{dataset_id}", status_code=204)
async def delete_dataset(
    dataset_id: str, workspace_id: str, user: dict = Depends(get_current_user)
) -> None:
    await require_workspace(workspace_id, user)
    deleted = await dataset_service.delete_dataset(workspace_id, dataset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="dataset not found")
