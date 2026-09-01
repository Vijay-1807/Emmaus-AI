import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.integrations import telegram

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=503, detail="telegram bot not configured")
    if settings.telegram_webhook_secret:
        expected = settings.telegram_webhook_secret
        provided = x_telegram_bot_api_secret_token or ""
        if not hmac.compare_digest(expected, provided):
            raise HTTPException(status_code=403, detail="invalid webhook secret")
    try:
        update = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON payload")
    try:
        await telegram.handle_update(update)
    except Exception as exc:
        import logging

        logging.getLogger("vedax.telegram").error("webhook handling failed: %s", exc, exc_info=True)
    return {"ok": True}


@router.get("/status")
async def telegram_status(user: dict = Depends(get_current_user)):
    settings = get_settings()
    if not settings.telegram_bot_token:
        return {"configured": False}
    try:
        info = await telegram.webhook_info()
        return {"configured": True, "webhook": info}
    except Exception as exc:
        return {"configured": True, "error": str(exc)[:200]}
