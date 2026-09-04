"""Create MongoDB Atlas Search indexes for Emmaus AI hybrid retrieval.

Run once after your Atlas cluster is reachable:
    uv run python scripts/setup_search_indexes.py

Requires MONGODB_URI in the environment (.env is loaded automatically).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo.asynchronous.mongo_client import AsyncMongoClient
from pymongo.errors import OperationFailure

from app.core.config import get_settings

def vector_index(dimensions: int) -> dict:
    return {
    "name": "vector_index",
    "type": "vectorSearch",
    "definition": {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": dimensions,
                "similarity": "cosine",
            },
            {"type": "filter", "path": "workspace_id"},
            {"type": "filter", "path": "document_id"},
            {"type": "filter", "path": "source_type"},
        ]
    },
    }

LEXICAL_INDEX = {
    "name": "lexical_index",
    "type": "search",
    "definition": {
        "mappings": {
            "dynamic": False,
            "fields": {
                "content": {"type": "string"},
                "workspace_id": {"type": "token"},
                "document_id": {"type": "token"},
                "source_type": {"type": "token"},
                "document_name": {"type": "string"},
            }
        }
    },
}


async def main() -> None:
    settings = get_settings()
    dimensions = (
        settings.gemini_embedding_dimensions
        if settings.embedding_provider == "gemini"
        else settings.embedding_dimensions
    )
    indexes = (vector_index(dimensions), LEXICAL_INDEX)
    print(f"configuring indexes for {settings.embedding_provider} embeddings ({dimensions} dimensions)")
    client = AsyncMongoClient(settings.mongodb_uri)
    try:
        db = client[settings.mongodb_db]
        try:
            existing = await db.command({"listSearchIndexes": "document_chunks"})
        except OperationFailure as exc:
            if exc.code == 59:
                print(
                    "Atlas Search index commands are unavailable on this connection. "
                    "Create vector_index and lexical_index in the Atlas UI."
                )
                return
            raise
        existing_names = {doc["name"] for doc in existing.get("cursor", {}).get("firstBatch", [])}
        for index in indexes:
            if index["name"] in existing_names:
                await db.command({
                    "updateSearchIndex": "document_chunks",
                    "name": index["name"],
                    "definition": index["definition"],
                })
                print(f"updated search index '{index['name']}'")
            else:
                await db.command({"createSearchIndexes": "document_chunks", "indexes": [index]})
                print(f"created search index '{index['name']}'")
    finally:
        await client.close()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
