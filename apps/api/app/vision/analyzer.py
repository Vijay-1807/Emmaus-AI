import base64
import logging
from typing import Any

from app.providers.base import RunContext, TaskType
from app.providers.registry import get_model_router

logger = logging.getLogger("vedax.vision")

OCR_PROMPT = """You are an OCR engine. Transcribe all text visible in this image exactly.
If the image contains handwriting, transcribe it as faithfully as possible.
Respond ONLY with JSON: {"text": "<full transcription>", "confidence": <0.0-1.0>}"""

ANALYSIS_PROMPT = """Analyze this image for a knowledge-analysis platform.
Respond ONLY with JSON:
{
  "description": "<1-3 sentence summary of what this image shows>",
  "extracted_text": "<all visible text, or empty string>",
  "is_handwritten": <true|false>,
  "key_observations": ["<observation 1>", "<observation 2>", "..."],
  "confidence": <0.0-1.0>,
  "content_type": "text|chart|diagram|photo|handwriting|screenshot|mixed",
  "regions": [{"type": "text|chart|table|image|heading", "description": "<short>", "confidence": <0.0-1.0>}]
}"""


def _image_block(image_bytes: bytes, mime: str) -> dict[str, Any]:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


async def ocr_image(image_bytes: bytes, mime: str = "image/png", ctx: RunContext | None = None) -> dict[str, Any]:
    router = get_model_router()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": OCR_PROMPT},
                _image_block(image_bytes, mime),
            ],
        }
    ]
    try:
        data, _ = await router.complete_json(messages, task=TaskType.VISION, ctx=ctx)
        return {
            "text": str(data.get("text", "")).strip(),
            "confidence": float(data.get("confidence", 0.8)),
        }
    except Exception as exc:
        logger.error("vision OCR failed: %s", exc)
        return {"text": "", "confidence": 0.0, "error": str(exc)[:200]}


async def analyze_image(
    image_bytes: bytes, mime: str = "image/png", ctx: RunContext | None = None
) -> dict[str, Any]:
    router = get_model_router()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": ANALYSIS_PROMPT},
                _image_block(image_bytes, mime),
            ],
        }
    ]
    try:
        data, _ = await router.complete_json(messages, task=TaskType.VISION, ctx=ctx)
        return {
            "description": str(data.get("description", "")),
            "extracted_text": str(data.get("extracted_text", "")),
            "is_handwritten": bool(data.get("is_handwritten", False)),
            "key_observations": [str(o) for o in data.get("key_observations", [])][:10],
            "confidence": float(data.get("confidence", 0.8)),
            "content_type": str(data.get("content_type", "text")),
            "regions": [
                {
                    "type": str(r.get("type", "text")),
                    "description": str(r.get("description", "")),
                    "confidence": float(r.get("confidence", 0.5)),
                }
                for r in (data.get("regions") or [])[:10]
            ],
        }
    except Exception as exc:
        logger.error("vision analysis failed: %s", exc)
        return {"description": "", "extracted_text": "", "is_handwritten": False,
                "key_observations": [], "confidence": 0.0, "content_type": "text",
                "regions": [], "error": str(exc)[:200]}


def format_analysis_for_indexing(filename: str, analysis: dict[str, Any]) -> str:
    lines = [f"Image: {filename}"]
    content_type = analysis.get("content_type", "text")
    if content_type:
        lines.append(f"Content type: {content_type}")
    if analysis.get("description"):
        lines.append(f"Description: {analysis['description']}")
    if analysis.get("is_handwritten"):
        lines.append("Content type: handwritten note")
    if analysis.get("extracted_text"):
        lines.append(f"Extracted text:\n{analysis['extracted_text']}")
    if analysis.get("key_observations"):
        lines.append("Key observations:")
        lines.extend(f"- {o}" for o in analysis["key_observations"])
    regions = analysis.get("regions", [])
    if regions:
        lines.append("Detected regions:")
        for r in regions:
            lines.append(f"  - [{r.get('type', '?')}] {r.get('description', '')}")
    return "\n".join(lines)
