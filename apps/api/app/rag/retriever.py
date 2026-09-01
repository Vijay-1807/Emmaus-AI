import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings
from app.core.db import get_db
from app.observability.langfuse import record_event, record_generation
from app.rag.embeddings import get_embedding_service

logger = logging.getLogger("vedax.retriever")

VECTOR_INDEX = "vector_index"
LEXICAL_INDEX = "lexical_index"

PROJECTION = {
    "content": 1,
    "document_id": 1,
    "document_name": 1,
    "source_type": 1,
    "page": 1,
    "section": 1,
    "workspace_id": 1,
}


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    document_name: str
    source_type: str
    content: str
    page: int | None = None
    section: str | None = None
    vector_score: float = 0.0
    lexical_score: float = 0.0
    fused_score: float = 0.0
    rerank_score: float | None = None
    media_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def best_score(self) -> float:
        return self.rerank_score if self.rerank_score is not None else self.fused_score


def rrf_fuse(
    vector_results: list[RetrievedChunk],
    lexical_results: list[RetrievedChunk],
    k: int = 60,
) -> list[RetrievedChunk]:
    merged: dict[str, RetrievedChunk] = {}
    scores: dict[str, float] = {}
    for results in (vector_results, lexical_results):
        for rank, chunk in enumerate(results):
            if chunk.chunk_id not in merged:
                merged[chunk.chunk_id] = chunk
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank + 1)
    for chunk_id, score in scores.items():
        merged[chunk_id].fused_score = round(score, 6)
    return sorted(merged.values(), key=lambda c: c.fused_score, reverse=True)


class Retriever:
    def __init__(self):
        self.settings = get_settings()

    async def retrieve(
        self,
        workspace_id: str,
        query: str,
        *,
        mode: str = "hybrid_rerank",
        top_k: int | None = None,
        document_ids: list[str] | None = None,
        query_vector: list[float] | None = None,
        ctx: Any = None,
    ) -> list[RetrievedChunk]:
        trace = getattr(ctx, "langfuse_trace", None) if ctx else None
        top_k = top_k or self.settings.final_top_k
        vector_results: list[RetrievedChunk] = []
        lexical_results: list[RetrievedChunk] = []

        if mode in ("vector", "hybrid", "hybrid_rerank"):
            t0 = time.perf_counter()
            vector_results = await self.vector_search(
                workspace_id, query, query_vector=query_vector, document_ids=document_ids
            )
            record_event(trace, name="vector_search", event_type="retrieval", metadata={
                "query": query[:200], "mode": mode, "results": len(vector_results),
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            })
        if mode in ("hybrid", "hybrid_rerank"):
            t0 = time.perf_counter()
            lexical_results = await self.lexical_search(
                workspace_id, query, document_ids=document_ids
            )
            record_event(trace, name="lexical_search", event_type="retrieval", metadata={
                "query": query[:200], "mode": mode, "results": len(lexical_results),
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            })

        if mode == "vector":
            fused = sorted(vector_results, key=lambda c: c.vector_score, reverse=True)
        else:
            fused = rrf_fuse(vector_results, lexical_results, self.settings.rrf_k)
            record_event(trace, name="rrf_fusion", event_type="retrieval", metadata={
                "vector_count": len(vector_results), "lexical_count": len(lexical_results),
                "fused_count": len(fused),
            })

        if mode == "hybrid_rerank" and fused:
            from app.rag.reranker import get_reranker

            reranker = get_reranker()
            fused = await reranker.rerank(query, fused, top_k=top_k, ctx=ctx)

        record_event(trace, name="retrieve_final", event_type="retrieval", metadata={
            "query": query[:200], "mode": mode, "final_count": len(fused[:top_k]),
        })
        return fused[:top_k]

    async def vector_search(
        self,
        workspace_id: str,
        query: str,
        *,
        query_vector: list[float] | None = None,
        limit: int | None = None,
        document_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        db = get_db()
        if query_vector is None:
            query_vector = (await get_embedding_service().embed([query]))[0]
        limit = limit or self.settings.vector_search_top_k
        search_filter: dict[str, Any] = {"workspace_id": workspace_id}
        if document_ids:
            search_filter["document_id"] = {"$in": document_ids}
        pipeline = [
            {
                "$vectorSearch": {
                    "index": VECTOR_INDEX,
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": max(limit * 8, 100),
                    "limit": limit,
                    "filter": search_filter,
                }
            },
            {"$project": {**PROJECTION, "score": {"$meta": "vectorSearchScore"}}},
        ]
        try:
            cursor = db.document_chunks.aggregate(pipeline)
            return [
                RetrievedChunk(
                    chunk_id=str(doc["_id"]),
                    document_id=doc["document_id"],
                    document_name=doc.get("document_name", ""),
                    source_type=doc.get("source_type", "document"),
                    content=doc.get("content", ""),
                    page=doc.get("page"),
                    section=doc.get("section"),
                    vector_score=round(float(doc.get("score", 0.0)), 4),
                )
                async for doc in cursor
            ]
        except Exception as exc:
            logger.error("vector search failed: %s", exc)
            return []

    async def lexical_search(
        self,
        workspace_id: str,
        query: str,
        *,
        limit: int | None = None,
        document_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        db = get_db()
        limit = limit or self.settings.lexical_search_top_k
        clauses: list[dict] = [{"equals": {"path": "workspace_id", "value": workspace_id}}]
        if document_ids:
            clauses.append({"in": {"path": "document_id", "value": document_ids}})
        pipeline = [
            {
                "$search": {
                    "index": LEXICAL_INDEX,
                    "compound": {
                        "filter": clauses,
                        "should": [{"text": {"query": query, "path": "content"}}],
                    },
                }
            },
            {"$project": {**PROJECTION, "score": {"$meta": "searchScore"}}},
            {"$limit": limit},
        ]
        try:
            cursor = db.document_chunks.aggregate(pipeline)
            return [
                RetrievedChunk(
                    chunk_id=str(doc["_id"]),
                    document_id=doc["document_id"],
                    document_name=doc.get("document_name", ""),
                    source_type=doc.get("source_type", "document"),
                    content=doc.get("content", ""),
                    page=doc.get("page"),
                    section=doc.get("section"),
                    lexical_score=round(float(doc.get("score", 0.0)), 4),
                )
                async for doc in cursor
            ]
        except Exception as exc:
            logger.error("lexical search failed: %s", exc)
            return []

    async def health(self) -> dict[str, Any]:
        db = get_db()
        vector_ok = True
        lexical_ok = True
        error = ""
        try:
            embedding = (await get_embedding_service().embed(["health check"]))[0]
            await db.document_chunks.aggregate(
                [
                    {
                        "$vectorSearch": {
                            "index": VECTOR_INDEX,
                            "path": "embedding",
                            "queryVector": embedding,
                            "numCandidates": 10,
                            "limit": 1,
                        }
                    },
                    {"$limit": 1},
                ]
            ).to_list(length=1)
        except Exception as exc:
            vector_ok = False
            error = str(exc)[:200]
        try:
            await db.document_chunks.aggregate(
                [
                    {
                        "$search": {
                            "index": LEXICAL_INDEX,
                            "compound": {"should": [{"text": {"query": "health", "path": "content"}}]},
                        }
                    },
                    {"$limit": 1},
                ]
            ).to_list(length=1)
        except Exception as exc:
            lexical_ok = False
            error = error or str(exc)[:200]
        return {"vector_index_ok": vector_ok, "lexical_index_ok": lexical_ok, "error": error}


_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever
