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


async def _transcribe_sarvam(audio_bytes: bytes, filename: str, mime: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.has_sarvam:
        raise TranscriptionError("sarvam not configured")
    client = AsyncOpenAI(api_key=settings.sarvam_api_key, base_url=settings.sarvam_base_url)
    response = await client.audio.transcriptions.create(
        model=settings.sarvam_stt_model,
        file=(filename, audio_bytes, mime),
    )
    return {"text": (response.text or "").strip(), "provider": "sarvam"}


async def _transcribe_deepgram(audio_bytes: bytes, filename: str, mime: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.has_deepgram:
        raise TranscriptionError("deepgram not configured")
    client = AsyncOpenAI(api_key=settings.deepgram_api_key, base_url=settings.deepgram_base_url)
    response = await client.audio.transcriptions.create(
        model=settings.deepgram_stt_model,
        file=(filename, audio_bytes, mime),
    )
    return {"text": (response.text or "").strip(), "provider": "deepgram"}


async def _transcribe_groq(audio_bytes: bytes, filename: str, mime: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.has_groq:
        raise TranscriptionError("groq not configured")
    client = AsyncOpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url)
    response = await client.audio.transcriptions.create(
        model=settings.groq_stt_model,
        file=(filename, audio_bytes, mime),
    )
    return {"text": (response.text or "").strip(), "provider": "groq"}


STT_CHAIN = [
    ("sarvam", _transcribe_sarvam),
    ("deepgram", _transcribe_deepgram),
    ("groq", _transcribe_groq),
]


async def transcribe_audio(
    audio_bytes: bytes, filename: str, mime: str | None = None
) -> dict[str, Any]:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".webm"
    content_type = mime or MIME_BY_EXT.get(ext, "audio/webm")

    errors: list[str] = []
    for name, fn in STT_CHAIN:
        try:
            result = await fn(audio_bytes, filename, content_type)
            if result.get("text"):
                return result
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            logger.warning("STT provider %s failed: %s", name, exc)

    raise TranscriptionError(
        f"all STT providers failed: {'; '.join(errors)}"
    )
