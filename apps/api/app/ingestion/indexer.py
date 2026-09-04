import logging
import uuid
from datetime import datetime, timezone

from app.core.db import get_db
from app.ingestion.chunker import ChunkData
from app.rag.embeddings import EmbeddingService

logger = logging.getLogger("vedax.indexer")

BATCH_SIZE = 64


async def index_chunks(
    workspace_id: str,
    document_id: str,
    document_name: str,
    source_type: str,
    chunks: list[ChunkData],
    embedding_service: EmbeddingService,
    embedding_model: str,
) -> int:
    db = get_db()
    if not chunks:
        return 0
    texts = [chunk.content for chunk in chunks]
    vectors = await embedding_service.embed(texts)
    if len(vectors) != len(chunks):
        raise ValueError(
            f"embedding provider returned {len(vectors)} vectors for {len(chunks)} chunks"
        )
    descriptor = embedding_service.descriptor
    expected_dimensions = descriptor.dimensions if descriptor else len(vectors[0])
    actual_model = descriptor.model if descriptor else embedding_model
    if any(len(vector) != expected_dimensions for vector in vectors):
        raise ValueError(f"embedding dimensions do not match expected size {expected_dimensions}")
    now = datetime.now(timezone.utc)
    inserted = 0
    for start in range(0, len(chunks), BATCH_SIZE):
        batch_chunks = chunks[start : start + BATCH_SIZE]
        batch_vectors = vectors[start : start + BATCH_SIZE]
        documents = [
            {
                "_id": uuid.uuid4().hex,
                "workspace_id": workspace_id,
                "document_id": document_id,
                "document_name": document_name,
                "source_type": source_type,
                "chunk_index": chunk.position,
                "content": chunk.content,
                "page": chunk.page,
                "section": chunk.section,
                "heading": chunk.heading,
                "parent_context": chunk.parent_context,
                "chunk_type": chunk.chunk_type,
                "metadata": chunk.metadata,
                "embedding": vector,
                "embedding_model": actual_model,
                "embedding_provider": descriptor.backend if descriptor else "unknown",
                "embedding_dimensions": len(vector),
                "created_at": now,
            }
            for chunk, vector in zip(batch_chunks, batch_vectors)
        ]
        await db.document_chunks.insert_many(documents)
        inserted += len(documents)
    logger.info("indexed %s chunks for document %s", inserted, document_id)
    return inserted


async def delete_document_chunks(document_id: str) -> int:
    db = get_db()
    result = await db.document_chunks.delete_many({"document_id": document_id})
    return result.deleted_count
