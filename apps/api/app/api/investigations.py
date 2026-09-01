from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user, require_workspace
from app.core.db import get_db
from app.models.schemas import InvestigationOut

router = APIRouter(prefix="/investigations", tags=["investigations"])


def to_out(investigation: dict) -> InvestigationOut:
    return InvestigationOut(
        id=investigation["_id"],
        workspace_id=investigation["workspace_id"],
        conversation_id=investigation.get("conversation_id", ""),
        question=investigation.get("question", ""),
        answer=investigation.get("answer", ""),
        capabilities=investigation.get("capabilities", []),
        citations=investigation.get("citations", []),
        charts=investigation.get("charts", []),
        evidence=investigation.get("evidence", []),
        confidence=investigation.get("confidence"),
        model_runs=investigation.get("model_runs", []),
        tool_calls=len(investigation.get("tool_runs", [])),
        latency_ms=investigation.get("latency_ms", 0),
        created_at=investigation["created_at"],
    )


@router.get("", response_model=list[InvestigationOut])
async def list_investigations(
    workspace_id: str, limit: int = 50, user: dict = Depends(get_current_user)
) -> list[InvestigationOut]:
    await require_workspace(workspace_id, user)
    db = get_db()
    cursor = (
        db.investigations.find({"workspace_id": workspace_id})
        .sort("created_at", -1)
        .limit(min(limit, 200))
    )
    return [to_out(i) async for i in cursor]


@router.get("/{investigation_id}", response_model=InvestigationOut)
async def get_investigation(
    investigation_id: str, workspace_id: str, user: dict = Depends(get_current_user)
) -> InvestigationOut:
    await require_workspace(workspace_id, user)
    db = get_db()
    investigation = await db.investigations.find_one(
        {"_id": investigation_id, "workspace_id": workspace_id}
    )
    if not investigation:
        raise HTTPException(status_code=404, detail="investigation not found")
    return to_out(investigation)
