from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.api.deps import get_current_user, require_workspace
from app.models.schemas import DatasetOut
from app.services import dataset_service

router = APIRouter(prefix="/datasets", tags=["datasets"])


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
    body: dict,
    user: dict = Depends(get_current_user),
) -> dict:
    source_ws = body.get("source_workspace_id")
    dataset_id = body.get("dataset_id")
    target_ws = body.get("target_workspace_id")
    if not source_ws or not dataset_id or not target_ws:
        raise HTTPException(status_code=422, detail="source_workspace_id, dataset_id, and target_workspace_id are required")
    await require_workspace(source_ws, user)
    await require_workspace(target_ws, user)
    from app.core.db import get_db
    db = get_db()
    ds = await db.datasets.find_one({"_id": dataset_id, "workspace_id": source_ws})
    if not ds:
        raise HTTPException(status_code=404, detail="dataset not found in source workspace")
    from uuid import uuid4
    already = await db.datasets.find_one({"workspace_id": target_ws, "media.public_id": ds.get("media", {}).get("public_id")})
    if already:
        return {"dataset_id": already["_id"], "already_copied": True}
    import copy as _copy
    new_id = uuid4().hex
    new_ds = _copy.deepcopy(ds)
    new_ds["_id"] = new_id
    new_ds["workspace_id"] = target_ws
    await db.datasets.insert_one(new_ds)
    chunks = [c async for c in db.document_chunks.find({"document_id": dataset_id})]
    if chunks:
        for chunk in chunks:
            chunk["_id"] = uuid4().hex
            chunk["document_id"] = new_id
            chunk["workspace_id"] = target_ws
        await db.document_chunks.insert_many(chunks)
    return {"dataset_id": new_id, "already_copied": False}


@router.delete("/{dataset_id}", status_code=204)
async def delete_dataset(
    dataset_id: str, workspace_id: str, user: dict = Depends(get_current_user)
) -> None:
    await require_workspace(workspace_id, user)
    deleted = await dataset_service.delete_dataset(workspace_id, dataset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="dataset not found")
