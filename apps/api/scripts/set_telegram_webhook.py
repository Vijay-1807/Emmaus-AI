"""Register the Telegram webhook + command menu. Free, one command.

Usage (from apps/api):
    uv run python scripts/set_telegram_webhook.py https://<your-api-host>/api/telegram/webhook

Requires TELEGRAM_BOT_TOKEN (and TELEGRAM_WEBHOOK_SECRET in production) in .env.
"""

import asyncio
import sys

import httpx

from app.core.config import get_settings

COMMANDS = [
    {"command": "start", "description": "Welcome + create your workspace"},
    {"command": "help", "description": "How to use Emmaus AI"},
    {"command": "new", "description": "Start a fresh chat"},
    {"command": "stop", "description": "Cancel the running investigation"},
    {"command": "clear", "description": "Wipe all workspace data"},
    {"command": "history", "description": "Recent investigations"},
    {"command": "status", "description": "Workspace stats"},
    {"command": "generate", "description": "Generate an image: /generate <prompt>"},
]


async def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    settings = get_settings()
    if not settings.telegram_bot_token:
        print("TELEGRAM_BOT_TOKEN is not set in .env — create the bot with @BotFather first.")
        raise SystemExit(1)
    base = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    async with httpx.AsyncClient(timeout=30) as client:
        payload: dict = {"url": sys.argv[1], "allowed_updates": ["message", "edited_message", "callback_query"]}
        if settings.telegram_webhook_secret:
            payload["secret_token"] = settings.telegram_webhook_secret
        res = await client.post(f"{base}/setWebhook", json=payload)
        print("setWebhook:", res.status_code, res.text[:200])
        res = await client.post(f"{base}/setMyCommands", json={"commands": COMMANDS})
        print("setMyCommands:", res.status_code, res.text[:200])
        res = await client.post(f"{base}/getWebhookInfo", json={})
        print("getWebhookInfo:", res.status_code, res.text[:500])


if __name__ == "__main__":
    asyncio.run(main())
