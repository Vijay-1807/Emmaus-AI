"""Delete all Emmaus application records while preserving collections and indexes."""

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo.asynchronous.mongo_client import AsyncMongoClient

from app.core.config import get_settings


COLLECTIONS = (
    "conversations",
    "datasets",
    "document_chunks",
    "documents",
    "evaluation_runs",
    "investigations",
    "jobs",
    "media_assets",
    "messages",
    "model_runs",
    "refresh_tokens",
    "telegram_links",
    "tool_runs",
    "users",
    "workspaces",
)


async def clear_data(include_local_media: bool) -> None:
    settings = get_settings()
    client = AsyncMongoClient(settings.mongodb_uri)
    try:
        db = client[settings.mongodb_db]
        for name in COLLECTIONS:
            result = await db[name].delete_many({})
            print(f"{name}: deleted {result.deleted_count}")
    finally:
        await client.close()

    if include_local_media:
        media_dir = Path(__file__).resolve().parents[3] / "media"
        if media_dir.exists():
            shutil.rmtree(media_dir)
            media_dir.mkdir()
        print(f"local media cleared: {media_dir}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="confirm destructive deletion")
    parser.add_argument("--include-local-media", action="store_true")
    args = parser.parse_args()
    if not args.yes:
        raise SystemExit("Refusing to delete data without --yes")
    asyncio.run(clear_data(args.include_local_media))


if __name__ == "__main__":
    main()
