from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user, require_workspace
from app.models.schemas import ObservabilitySummary
from app.services import observability_service

router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/summary", response_model=ObservabilitySummary)
async def summary(
    workspace_id: str = Query(..., description="Workspace ID (required)"),
    user: dict = Depends(get_current_user),
) -> ObservabilitySummary:
    await require_workspace(workspace_id, user)
    data = await observability_service.summary(workspace_id)
    return ObservabilitySummary(**data)


@router.get("/traces")
async def traces(
    workspace_id: str = Query(..., description="Workspace ID (required)"),
    limit: int = Query(50, le=200),
    user: dict = Depends(get_current_user),
):
    await require_workspace(workspace_id, user)
    return await observability_service.recent_traces(workspace_id, limit)
