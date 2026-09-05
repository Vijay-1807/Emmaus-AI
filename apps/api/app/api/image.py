from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_user, require_workspace
from app.services.image_service import get_image_service

router = APIRouter(prefix="/image", tags=["image"])


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2048, description="Text prompt for image generation")
    steps: int = Field(default=4, ge=1, le=8, description="Number of inference steps (1-8)")
    seed: int | None = Field(default=None, description="Optional random seed for reproducibility")


class ImageGenerateResponse(BaseModel):
    success: bool
    image: str | None = None
    mime: str = "image/jpeg"
    error: str | None = None
    metadata: dict | None = None


@router.post("/generate", response_model=ImageGenerateResponse)
async def generate_image(
    payload: ImageGenerateRequest,
    workspace_id: str,
    user: dict = Depends(get_current_user),
) -> ImageGenerateResponse:
    """Generate an image using Cloudflare Workers AI FLUX.1 Schnell.

    Requires a valid workspace and authenticated user.
    The image is generated server-side and returned as base64.
    """
    await require_workspace(workspace_id, user)

    service = get_image_service()
    if not service.is_available:
        raise HTTPException(
            status_code=503,
            detail="Image generation is not configured. Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN.",
        )

    result = await service.generate(
        prompt=payload.prompt,
        steps=payload.steps,
        seed=payload.seed,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return ImageGenerateResponse(
        success=True,
        image=f"data:{result.image_mime};base64,{result.image_base64}",
        mime=result.image_mime,
        metadata=result.metadata,
    )


@router.get("/status")
async def image_generation_status(user: dict = Depends(get_current_user)) -> dict:
    """Check if image generation is available."""
    service = get_image_service()
    return {
        "available": service.is_available,
        "model": service.settings.cloudflare_image_model if service.is_available else None,
    }
