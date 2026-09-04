import logging
from typing import Any
import httpx
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


async def _transcribe_deepgram(audio_bytes: bytes, filename: str, mime: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.has_deepgram:
        raise TranscriptionError("deepgram not configured")
    model = settings.deepgram_stt_model or "nova-3"
    url = f"https://api.deepgram.com/v1/listen?model={model}&smart_format=true"
    headers = {
        "Authorization": f"Token {settings.deepgram_api_key}",
        "Content-Type": mime or "audio/wav",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(url, headers=headers, content=audio_bytes)
        if res.status_code != 200:
            raise TranscriptionError(f"Deepgram HTTP {res.status_code}: {res.text[:200]}")
        data = res.json()
        transcript = (
            data.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
            .get("transcript", "")
            .strip()
        )
        if not transcript:
            raise TranscriptionError("Deepgram returned empty transcript")
        return {"text": transcript, "provider": "deepgram", "model": model}


async def _transcribe_sarvam(audio_bytes: bytes, filename: str, mime: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.has_sarvam:
        raise TranscriptionError("sarvam not configured")
    url = "https://api.sarvam.ai/speech-to-text"
    headers = {"api-subscription-key": settings.sarvam_api_key}
    files = {"file": (filename, audio_bytes, mime)}
    data = {"model": settings.sarvam_stt_model or "saaras:v4"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(url, headers=headers, files=files, data=data)
        if res.status_code != 200:
            raise TranscriptionError(f"Sarvam HTTP {res.status_code}: {res.text[:200]}")
        transcript = (res.json().get("transcript") or "").strip()
        if not transcript:
            raise TranscriptionError("Sarvam returned empty transcript")
        return {"text": transcript, "provider": "sarvam", "model": data["model"]}


async def _transcribe_groq(audio_bytes: bytes, filename: str, mime: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.has_groq:
        raise TranscriptionError("groq not configured")
    client = AsyncOpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url)
    model = settings.groq_stt_model or "whisper-large-v3-turbo"
    response = await client.audio.transcriptions.create(
        model=model,
        file=(filename, audio_bytes, mime),
    )
    transcript = (response.text or "").strip()
    if not transcript:
        raise TranscriptionError("Groq returned empty transcript")
    return {"text": transcript, "provider": "groq", "model": model}


# Cascading priority: Deepgram (Primary) -> Sarvam (Indian/regional fallback) -> Groq Whisper (Global fallback)
STT_CHAIN = [
    ("deepgram", _transcribe_deepgram),
    ("sarvam", _transcribe_sarvam),
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
                logger.info("audio transcribed successfully using provider: %s", name)
                return result
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            logger.warning("STT provider %s failed: %s", name, exc)

    raise TranscriptionError(f"all STT providers failed: {'; '.join(errors)}")
