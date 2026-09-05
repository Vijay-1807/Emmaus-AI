import asyncio
import base64
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger("vedax.image")

# Cloudflare Workers AI FLUX.1 Schnell limits
MAX_PROMPT_LENGTH = 2048
MIN_STEPS = 1
MAX_STEPS = 8
DEFAULT_STEPS = 4
REQUEST_TIMEOUT = 120  # seconds


@dataclass
class ImageGenerationResult:
    success: bool
    image_base64: str | None = None
    image_mime: str = "image/jpeg"
    error: str | None = None
    metadata: dict[str, Any] | None = None


class ImageGenerationService:
    """Service for generating images using Cloudflare Workers AI FLUX.1 Schnell."""

    def __init__(self):
        self.settings = get_settings()
        self._configured = False

    @property
    def is_available(self) -> bool:
        return self.settings.has_cloudflare

    def _get_endpoint(self) -> str:
        account_id = self.settings.cloudflare_account_id
        model = self.settings.cloudflare_image_model
        return f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"

    async def generate(
        self,
        prompt: str,
        steps: int = DEFAULT_STEPS,
        seed: int | None = None,
    ) -> ImageGenerationResult:
        """Generate an image using Cloudflare Workers AI FLUX.1 Schnell.

        Args:
            prompt: Text prompt for image generation (max 2048 chars)
            steps: Number of inference steps (1-8, default 4)
            seed: Optional random seed for reproducibility

        Returns:
            ImageGenerationResult with base64 image data or error
        """
        if not self.is_available:
            return ImageGenerationResult(
                success=False,
                error="Cloudflare Workers AI is not configured. Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN.",
            )

        # Validate prompt
        if not prompt or not prompt.strip():
            return ImageGenerationResult(success=False, error="Prompt cannot be empty.")

        prompt = prompt.strip()
        if len(prompt) > MAX_PROMPT_LENGTH:
            return ImageGenerationResult(
                success=False,
                error=f"Prompt exceeds maximum length of {MAX_PROMPT_LENGTH} characters.",
            )

        # Validate steps
        steps = max(MIN_STEPS, min(MAX_STEPS, steps))

        # Build request payload
        payload: dict[str, Any] = {"prompt": prompt, "steps": steps}
        if seed is not None:
            payload["seed"] = seed

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(
                    self._get_endpoint(),
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.settings.cloudflare_api_token}",
                        "Content-Type": "application/json",
                    },
                )

                # Handle HTTP errors
                if response.status_code == 401:
                    return ImageGenerationResult(
                        success=False,
                        error="Cloudflare authentication failed. Check CLOUDFLARE_API_TOKEN.",
                    )
                if response.status_code == 403:
                    return ImageGenerationResult(
                        success=False,
                        error="Cloudflare quota exceeded or access denied.",
                    )
                if response.status_code == 429:
                    return ImageGenerationResult(
                        success=False,
                        error="Cloudflare rate limit exceeded. Try again later.",
                    )
                if response.status_code != 200:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("errors", [{}])[0].get("message", response.text[:200])
                    except Exception:
                        error_msg = response.text[:200]
                    return ImageGenerationResult(
                        success=False,
                        error=f"Cloudflare API error ({response.status_code}): {error_msg}",
                    )

                # Parse response
                data = response.json()

                if not data.get("success"):
                    errors = data.get("errors", [])
                    error_msg = errors[0].get("message", "Unknown Cloudflare error") if errors else "Unknown error"
                    return ImageGenerationResult(success=False, error=f"Cloudflare error: {error_msg}")

                result_data = data.get("result")
                if not result_data:
                    return ImageGenerationResult(
                        success=False,
                        error="Cloudflare returned empty result.",
                    )

                # Handle different response formats
                image_base64 = None
                image_mime = "image/jpeg"

                if isinstance(result_data, dict):
                    # Format: {"image": "base64...", "mime": "image/png"}
                    image_base64 = result_data.get("image")
                    image_mime = result_data.get("mime", "image/jpeg")
                elif isinstance(result_data, str):
                    # Direct base64 string
                    image_base64 = result_data

                if not image_base64:
                    return ImageGenerationResult(
                        success=False,
                        error="Cloudflare returned no image data.",
                    )

                # Clean base64 string (remove data URL prefix if present)
                if "," in image_base64 and image_base64.startswith("data:"):
                    image_base64 = image_base64.split(",", 1)[1]

                return ImageGenerationResult(
                    success=True,
                    image_base64=image_base64,
                    image_mime=image_mime,
                    metadata={
                        "model": self.settings.cloudflare_image_model,
                        "steps": steps,
                        "seed": seed,
                        "prompt_length": len(prompt),
                    },
                )

        except httpx.TimeoutException:
            return ImageGenerationResult(
                success=False,
                error="Cloudflare request timed out. Try a simpler prompt or fewer steps.",
            )
        except httpx.ConnectError:
            return ImageGenerationResult(
                success=False,
                error="Failed to connect to Cloudflare. Check network connectivity.",
            )
        except Exception as exc:
            logger.error("Image generation failed: %s", exc, exc_info=True)
            return ImageGenerationResult(
                success=False,
                error=f"Image generation failed: {str(exc)[:200]}",
            )


# Singleton instance
_image_service: ImageGenerationService | None = None


def get_image_service() -> ImageGenerationService:
    global _image_service
    if _image_service is None:
        _image_service = ImageGenerationService()
    return _image_service
