import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.api.deps import get_current_user, require_workspace
from app.core.config import get_settings
from app.core.db import get_db
from app.models.schemas import MediaAssetOut
from app.services.media_service import MediaService, kind_for

router = APIRouter(prefix="/media", tags=["media"])


def to_out(media: dict) -> MediaAssetOut:
    return MediaAssetOut(
        id=media["_id"],
        workspace_id=media["workspace_id"],
        kind=media["kind"],
        filename=media["filename"],
        url=media.get("url", ""),
        transcript=media.get("transcript"),
        analysis=media.get("analysis"),
        size_bytes=media.get("size_bytes", 0),
        created_at=media["created_at"],
    )


@router.post("/upload", response_model=MediaAssetOut, status_code=201)
async def upload_media(
    file: UploadFile,
    workspace_id: str,
    user: dict = Depends(get_current_user),
) -> MediaAssetOut:
    await require_workspace(workspace_id, user)
    settings = get_settings()
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.max_upload_bytes:
            raise HTTPException(status_code=400, detail=f"file exceeds {settings.max_upload_mb}MB limit")
        chunks.append(chunk)
    data = b"".join(chunks)
    filename = file.filename or "capture.webm"
    kind = kind_for(filename, file.content_type)
    if kind == "file":
        raise HTTPException(status_code=400, detail="media upload accepts images and audio only")

    media_service = MediaService()
    stored = await media_service.upload(data, filename, workspace_id, kind)

    analysis = None
    transcript = None
    if kind == "image":
        from app.vision.analyzer import analyze_image

        analysis = await analyze_image(data, file.content_type or "image/png")
    elif kind == "audio":
        from app.audio.transcriber import transcribe_audio

        try:
            result = await transcribe_audio(data, filename, file.content_type)
            transcript = result["text"]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    media = {
        "_id": uuid.uuid4().hex,
        "workspace_id": workspace_id,
        "owner_id": user["_id"],
        "kind": kind,
        "filename": filename,
        "url": stored.url,
        "public_id": stored.public_id,
        "storage_mode": stored.mode,
        "transcript": transcript,
        "analysis": analysis,
        "size_bytes": len(data),
        "created_at": datetime.now(timezone.utc),
    }
    db = get_db()
    await db.media_assets.insert_one(media)
    return to_out(media)


@router.get("", response_model=list[MediaAssetOut])
async def list_media(
    workspace_id: str, user: dict = Depends(get_current_user)
) -> list[MediaAssetOut]:
    await require_workspace(workspace_id, user)
    db = get_db()
    cursor = db.media_assets.find({"workspace_id": workspace_id}).sort("created_at", -1)
    items = await cursor.to_list(length=100)
    return [to_out(m) for m in items]


@router.get("/{media_id}", response_model=MediaAssetOut)
async def get_media(
    media_id: str, workspace_id: str, user: dict = Depends(get_current_user)
) -> MediaAssetOut:
    await require_workspace(workspace_id, user)
    db = get_db()
    media = await db.media_assets.find_one({"_id": media_id, "workspace_id": workspace_id})
    if not media:
        raise HTTPException(status_code=404, detail="media asset not found")
    return to_out(media)


@router.delete("/{media_id}", status_code=204)
async def delete_media(
    media_id: str, workspace_id: str, user: dict = Depends(get_current_user)
) -> None:
    await require_workspace(workspace_id, user)
    db = get_db()
    media = await db.media_assets.find_one({"_id": media_id, "workspace_id": workspace_id})
    if not media:
        raise HTTPException(status_code=404, detail="media asset not found")
    from app.services.media_service import MediaService, StoredAsset

    if media.get("public_id"):
        try:
            svc = MediaService()
            asset = StoredAsset(
                public_id=media["public_id"],
                url=media.get("url", ""),
                resource_type=media.get("kind", "file"),
                mode=media.get("storage_mode", "local"),
            )
            await svc.delete(asset)
        except Exception:
            pass
    await db.media_assets.delete_one({"_id": media_id, "workspace_id": workspace_id})
