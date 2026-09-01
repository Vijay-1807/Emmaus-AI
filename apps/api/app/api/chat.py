import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.agents.orchestrator import run_investigation
from app.api.deps import get_current_user, require_workspace
from app.core.db import get_db
from app.models.schemas import ChatRequest, ConversationOut
from app.services.auth_service import get_user_by_id

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/stream")
async def chat_stream(payload: ChatRequest, user: dict = Depends(get_current_user)):
    await require_workspace(payload.workspace_id, user)
    if not payload.message.strip() and not payload.audio_media_id:
        raise HTTPException(status_code=400, detail="message or audio input required")

    async def event_generator():
        async for event in run_investigation(
            workspace_id=payload.workspace_id,
            user_id=user["_id"],
            question=payload.message.strip(),
            conversation_id=payload.conversation_id,
            attachment_ids=payload.attachment_ids,
            audio_media_id=payload.audio_media_id,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        yield "data: [STREAM_END]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    workspace_id: str, user: dict = Depends(get_current_user)
) -> list[ConversationOut]:
    await require_workspace(workspace_id, user)
    db = get_db()
    cursor = (
        db.conversations.find({"workspace_id": workspace_id})
        .sort("updated_at", -1)
        .limit(50)
    )
    return [
        ConversationOut(
            id=c["_id"], workspace_id=c["workspace_id"], title=c.get("title", ""), updated_at=c["updated_at"]
        )
        async for c in cursor
    ]


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    workspace_id: str,
    user: dict = Depends(get_current_user),
):
    await require_workspace(workspace_id, user)
    db = get_db()
    conversation = await db.conversations.find_one(
        {"_id": conversation_id, "workspace_id": workspace_id}
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="conversation not found")
    cursor = (
        db.messages.find({"conversation_id": conversation_id}).sort("created_at", 1).limit(200)
    )
    messages = []
    async for message in cursor:
        messages.append(
            {
                "id": message["_id"],
                "role": message["role"],
                "content": message.get("content", ""),
                "attachment_ids": message.get("attachment_ids", []),
                "citations": message.get("citations", []),
                "charts": message.get("charts", []),
                "confidence": message.get("confidence"),
                "investigation_id": message.get("investigation_id"),
                "created_at": message.get("created_at"),
            }
        )
    return {"conversation": {"id": conversation["_id"], "title": conversation.get("title", "")}, "messages": messages}
