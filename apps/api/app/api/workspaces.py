from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.models.schemas import WorkspaceIn, WorkspaceOut, WorkspaceUpdate
from app.services import workspace_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def to_out(workspace: dict) -> WorkspaceOut:
    return WorkspaceOut(
        id=workspace["_id"],
        name=workspace["name"],
        description=workspace.get("description", ""),
        owner_id=workspace["owner_id"],
        document_count=workspace.get("document_count", 0),
        dataset_count=workspace.get("dataset_count", 0),
        investigation_count=workspace.get("investigation_count", 0),
        created_at=workspace["created_at"],
    )


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(user: dict = Depends(get_current_user)) -> list[WorkspaceOut]:
    return [to_out(w) for w in await workspace_service.list_workspaces(user["_id"])]


@router.post("", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    payload: WorkspaceIn, user: dict = Depends(get_current_user)
) -> WorkspaceOut:
    workspace = await workspace_service.create_workspace(
        user["_id"], payload.name, payload.description
    )
    return to_out(workspace)


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(
    workspace_id: str, user: dict = Depends(get_current_user)
) -> WorkspaceOut:
    workspace = await workspace_service.get_workspace(workspace_id, user["_id"])
    if not workspace:
        raise HTTPException(status_code=404, detail="workspace not found")
    workspace.setdefault("document_count", 0)
    workspace.setdefault("dataset_count", 0)
    workspace.setdefault("investigation_count", 0)
    return to_out(workspace)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(
    workspace_id: str,
    payload: WorkspaceUpdate,
    user: dict = Depends(get_current_user),
) -> WorkspaceOut:
    workspace = await workspace_service.update_workspace(
        workspace_id, user["_id"], payload.model_dump()
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="workspace not found")
    return to_out(workspace)


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str, user: dict = Depends(get_current_user)) -> None:
    deleted = await workspace_service.delete_workspace(workspace_id, user["_id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="workspace not found")


@router.post("/{workspace_id}/clear")
async def clear_workspace(workspace_id: str, user: dict = Depends(get_current_user)) -> dict:
    summary = await workspace_service.clear_workspace_data(workspace_id, user["_id"])
    if summary is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return {"message": "workspace storage cleared successfully", "details": summary}


@router.get("/{workspace_id}/storage-summary")
async def get_storage_summary(workspace_id: str, user: dict = Depends(get_current_user)) -> dict:
    summary = await workspace_service.get_workspace_storage_summary(workspace_id, user["_id"])
    if summary is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return summary
