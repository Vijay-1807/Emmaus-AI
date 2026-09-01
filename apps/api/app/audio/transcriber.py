import logging
from typing import Any

from openai import AsyncOpenAI

from app.core.config import get_settings

logger = logging.getLogger("vedax.audio")

MIME_BY_EXT = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
}


class TranscriptionError(RuntimeError):
    pass


async def transcribe_audio(
    audio_bytes: bytes, filename: str, mime: str | None = None
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.has_groq:
        raise TranscriptionError(
            "audio transcription requires GROQ_API_KEY (Groq Whisper endpoint)"
        )
    client = AsyncOpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url)
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".webm"
    content_type = mime or MIME_BY_EXT.get(ext, "audio/webm")
    try:
        response = await client.audio.transcriptions.create(
            model=settings.groq_stt_model,
            file=(filename, audio_bytes, content_type),
        )
        return {"text": (response.text or "").strip()}
    except Exception as exc:
        logger.error("transcription failed: %s", exc)
        raise TranscriptionError(f"transcription failed: {exc}") from exc
