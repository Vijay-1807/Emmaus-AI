import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger("vedax.media")

MEDIA_DIR = Path("media")
IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/jpg"}
_CLOUDINARY_UNAVAILABLE = False


@dataclass
class StoredAsset:
    public_id: str
    url: str
    resource_type: str
    mode: str
    bytes_path: str | None = None


def _mime_for(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".pdf"):
        return "application/pdf"
    if lower.endswith(".csv"):
        return "text/csv"
    if lower.endswith((".xlsx", ".xls")):
        return "application/vnd.ms-excel"
    if lower.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lower.endswith(".wav"):
        return "audio/wav"
    if lower.endswith(".mp3"):
        return "audio/mpeg"
    if lower.endswith(".m4a"):
        return "audio/mp4"
    if lower.endswith(".ogg"):
        return "audio/ogg"
    if lower.endswith(".flac"):
        return "audio/flac"
    if lower.endswith(".webm"):
        return "audio/webm"
    return "application/octet-stream"


def kind_for(filename: str, content_type: str | None = None) -> str:
    mime = content_type or _mime_for(filename)
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    return "file"


class MediaService:
    def __init__(self):
        global _CLOUDINARY_UNAVAILABLE
        self.settings = get_settings()
        mode = self.settings.media_storage
        if mode == "auto":
            mode = "cloudinary" if self.settings.has_cloudinary else "local"
        self.mode = mode
        self._cloudinary_configured = False
        # Once Cloudinary rejects us for auth/permissions, stop trying —
        # every upload would warn + retry otherwise.
        self._cloudinary_dead = _CLOUDINARY_UNAVAILABLE

    @property
    def cloudinary_usable(self) -> bool:
        return self.mode == "cloudinary" and not self._cloudinary_dead

    def _mark_cloudinary_failed(self, message: str) -> None:
        global _CLOUDINARY_UNAVAILABLE
        self._cloudinary_dead = True
        _CLOUDINARY_UNAVAILABLE = True
        logger.warning(
            "Cloudinary rejected uploads (%s). Fix: Cloudinary Dashboard -> "
            "Settings -> API Keys -> use a key with Upload(create) permission, "
            "or set MEDIA_STORAGE=local. Falling back to local storage for "
            "this service instance.",
            message[:200],
        )

    def _configure_cloudinary(self) -> None:
        if self._cloudinary_configured:
            return
        import cloudinary

        cloudinary.config(
            cloud_name=self.settings.cloudinary_cloud_name,
            api_key=self.settings.cloudinary_api_key,
            api_secret=self.settings.cloudinary_api_secret,
            secure=True,
        )
        self._cloudinary_configured = True

    async def upload(
        self,
        data: bytes,
        filename: str,
        workspace_id: str,
        resource_kind: str,
    ) -> StoredAsset:
        public_id = f"{workspace_id}/{uuid.uuid4().hex}-{filename}"
        if self.mode == "cloudinary" and not self._cloudinary_dead:
            return await self._upload_cloudinary(data, filename, public_id, resource_kind)
        return await self._upload_local(data, filename, public_id, resource_kind)

    async def _upload_cloudinary(
        self, data: bytes, filename: str, public_id: str, resource_kind: str
    ) -> StoredAsset:
        try:
            import re

            import cloudinary.uploader

            self._configure_cloudinary()
            # Cloudinary rejects spaces/parens/& in public IDs — slugify them.
            public_id = "/".join(
                re.sub(r"[^A-Za-z0-9_.-]", "_", part) for part in public_id.split("/")
            )
            resource_type = {"image": "image", "audio": "video", "file": "raw"}[resource_kind]
            result = await asyncio.to_thread(
                cloudinary.uploader.upload,
                data,
                public_id=public_id,
                resource_type=resource_type,
                folder="emmaus",
                use_filename=False,
                unique_filename=False,
            )
            return StoredAsset(
                public_id=result["public_id"],
                url=result["secure_url"],
                resource_type=resource_type,
                mode="cloudinary",
            )
        except Exception as exc:
            message = str(exc)
            if "forbidden" in message.lower() or "permission" in message.lower() or "unauthorized" in message.lower():
                self._mark_cloudinary_failed(message)
            else:
                logger.warning("Cloudinary upload failed (%s), falling back to local storage", message[:200])
            return await self._upload_local(data, filename, public_id, resource_kind)

    async def _upload_local(
        self, data: bytes, filename: str, public_id: str, resource_kind: str
    ) -> StoredAsset:
        safe_name = filename.replace("/", "_").replace("\\", "_").replace("..", "_")
        target_dir = MEDIA_DIR / workspace_dir(public_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{uuid.uuid4().hex[:8]}-{safe_name}"
        await asyncio.to_thread(path.write_bytes, data)
        url = f"/media/{path.as_posix().removeprefix('media/')}"
        return StoredAsset(
            public_id=public_id,
            url=url,
            resource_type=resource_kind,
            mode="local",
            bytes_path=str(path),
        )

    async def delete(self, asset: StoredAsset) -> None:
        if asset.mode == "cloudinary":
            import cloudinary.uploader

            self._configure_cloudinary()
            await asyncio.to_thread(
                cloudinary.uploader.destroy,
                asset.public_id,
                resource_type=asset.resource_type,
            )
        elif asset.bytes_path:
            path = Path(asset.bytes_path)
            await asyncio.to_thread(path.unlink, missing_ok=True)


def workspace_dir(public_id: str) -> str:
    return public_id.split("/")[0]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
