"""Create MongoDB Atlas Search indexes for VedaX AI hybrid retrieval.

Run once after your Atlas cluster is reachable:
    uv run python scripts/setup_search_indexes.py

Requires MONGODB_URI in the environment (.env is loaded automatically).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo.asynchronous import AsyncMongoClient

from app.core.config import get_settings

VECTOR_INDEX = {
    "name": "vector_index",
    "type": "vectorSearch",
    "definition": {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": 3072,
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
                "workspace_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "source_type": {"type": "keyword"},
                "document_name": {"type": "string"},
            }
        }
    },
}


async def main() -> None:
    settings = get_settings()
    if settings.embedding_dimensions != 768:
        VECTOR_INDEX["definition"]["fields"][0]["numDimensions"] = settings.embedding_dimensions
        print(f"using embedding dimensions from settings: {settings.embedding_dimensions}")
    client = AsyncMongoClient(settings.mongodb_uri)
    db = client[settings.mongodb_db]
    existing = await db.command({"listSearchIndexes": "document_chunks"})
    existing_names = {doc["name"] for doc in existing.get("cursor", {}).get("firstBatch", [])}
    for index in (VECTOR_INDEX, LEXICAL_INDEX):
        if index["name"] in existing_names:
            print(f"index '{index['name']}' already exists - skipping")
            continue
        await db.command({"createSearchIndexes": "document_chunks", "indexes": [index]})
        print(f"created search index '{index['name']}' (building on Atlas may take ~1 minute)")
    client.close()
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
