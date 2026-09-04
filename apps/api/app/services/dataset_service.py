import asyncio
import io
import logging
import uuid
from datetime import datetime, timezone

import pandas as pd

from app.core.config import get_settings
from app.core.db import get_db
from app.ingestion.chunker import chunk_markdown_text
from app.ingestion.indexer import delete_document_chunks, index_chunks
from app.ingestion.parser import build_dataset_text_summary
from app.rag.embeddings import get_embedding_service
from app.services.media_service import MediaService

logger = logging.getLogger("vedax.datasets")

DATASET_EXTS = {".csv", ".xlsx", ".xls"}
MAX_ROWS_STORED = 50_000


def now() -> datetime:
    return datetime.now(timezone.utc)


def load_dataframe(data: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    if lower.endswith(".csv"):
        return pd.read_csv(io.BytesIO(data))
    return pd.read_excel(io.BytesIO(data))


def records_from_df(df: pd.DataFrame) -> list[dict]:
    trimmed = df.head(MAX_ROWS_STORED)
    records: list[dict] = []
    total_chars = 0
    for record in trimmed.astype(object).where(pd.notna(trimmed), None).to_dict("records"):
        total_chars += len(str(record))
        if total_chars > 8_000_000 or len(records) >= MAX_ROWS_STORED:
            break
        records.append(record)
    return records


def profile_columns(df: pd.DataFrame) -> list[dict]:
    columns = []
    for column in df.columns:
        try:
            unique = int(df[column].nunique(dropna=True))
        except Exception:
            unique = 0
        columns.append(
            {
                "name": str(column),
                "dtype": str(df[column].dtype),
                "non_null": int(df[column].notna().sum()),
                "unique": unique,
            }
        )
    return columns


async def create_dataset(
    workspace_id: str, owner_id: str, filename: str, content_type: str, data: bytes
) -> dict:
    db = get_db()
    settings = get_settings()
    lower = filename.lower()
    if not any(lower.endswith(ext) for ext in DATASET_EXTS):
        raise ValueError("datasets must be .csv or .xlsx files")
    if len(data) > settings.max_upload_bytes:
        raise ValueError(f"file exceeds {settings.max_upload_mb}MB limit")

    media = MediaService()
    stored = await media.upload(data, filename, workspace_id, "file")
    dataset = {
        "_id": uuid.uuid4().hex,
        "workspace_id": workspace_id,
        "owner_id": owner_id,
        "filename": filename,
        "content_type": content_type or "text/csv",
        "status": "processing",
        "error": None,
        "num_rows": 0,
        "num_columns": 0,
        "columns": [],
        "sample_rows": [],
        "rows": [],
        "size_bytes": len(data),
        "media": {
            "url": stored.url,
            "public_id": stored.public_id,
            "mode": stored.mode,
            "resource_type": stored.resource_type,
        },
        "created_at": now(),
    }
    await db.datasets.insert_one(dataset)
    asyncio.create_task(_process_dataset(dataset["_id"], workspace_id, filename, data))
    return dataset


async def _process_dataset(dataset_id: str, workspace_id: str, filename: str, data: bytes) -> None:
    db = get_db()
    try:
        df = load_dataframe(data, filename)
        records = records_from_df(df)
        columns = profile_columns(df)
        sample = records[:25]
        summary = build_dataset_text_summary(filename, df)
        chunks = chunk_markdown_text(summary)
        if not chunks:
            raise ValueError("no searchable content could be extracted from this dataset")
        embedding_service = get_embedding_service()
        num_chunks = await index_chunks(
            workspace_id,
            dataset_id,
            filename,
            "dataset",
            chunks,
            embedding_service,
            embedding_service.settings.embedding_model,
        )
        _ = num_chunks
        await db.datasets.update_one(
            {"_id": dataset_id},
            {
                "$set": {
                    "status": "ready",
                    "num_rows": len(df),
                    "num_columns": len(df.columns),
                    "columns": columns,
                    "sample_rows": sample,
                    "rows": records,
                }
            },
        )
        logger.info("dataset %s processed (%s rows)", dataset_id, len(df))
    except Exception as exc:
        logger.error("dataset processing failed: %s", exc, exc_info=True)
        await db.datasets.update_one(
            {"_id": dataset_id}, {"$set": {"status": "failed", "error": str(exc)[:500]}}
        )


async def list_datasets(workspace_id: str, limit: int = 100) -> list[dict]:
    db = get_db()
    cursor = db.datasets.find({"workspace_id": workspace_id}).sort("created_at", -1).limit(limit)
    return [doc async for doc in cursor]


async def get_dataset(workspace_id: str, dataset_id: str) -> dict | None:
    db = get_db()
    return await db.datasets.find_one({"_id": dataset_id, "workspace_id": workspace_id})


async def delete_dataset(workspace_id: str, dataset_id: str) -> bool:
    db = get_db()
    dataset = await get_dataset(workspace_id, dataset_id)
    if not dataset:
        return False
    await delete_document_chunks(dataset_id)
    await db.datasets.delete_one({"_id": dataset_id})
    return True
