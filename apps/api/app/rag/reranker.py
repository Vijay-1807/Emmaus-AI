import logging
import time
from typing import Any

from app.observability.langfuse import record_event, record_generation
from app.providers.base import RunContext, TaskType
from app.providers.registry import get_model_router
from app.rag.retriever import RetrievedChunk

logger = logging.getLogger("vedax.reranker")

MAX_CANDIDATES = 25
SNIPPET_CHARS = 400

RERANK_PROMPT = """You are a relevance judge. Score how well each passage answers the question.
Question: {question}

Passages:
{passages}

Respond ONLY with JSON: {{"scores": [<score 0-10 for passage 1>, <score for passage 2>, ...]}}
Give 8-10 only to passages that directly answer the question with specific facts.
Give 4-7 to partially relevant background. Give 0-3 to irrelevant passages."""


class LLMReranker:
    async def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        top_k: int,
        ctx: RunContext | None = None,
    ) -> list[RetrievedChunk]:
        trace = getattr(ctx, "langfuse_trace", None) if ctx else None
        candidates = chunks[:MAX_CANDIDATES]
        passages = []
        for index, chunk in enumerate(candidates, start=1):
            snippet = chunk.content[:SNIPPET_CHARS].replace("\n", " ")
            page_str = f" p.{chunk.page}" if chunk.page is not None else ""
            passages.append(f"[{index}] ({chunk.document_name}{page_str}): {snippet}")
        prompt = RERANK_PROMPT.format(question=query, passages="\n".join(passages))
        t0 = time.perf_counter()
        try:
            router = get_model_router()
            data, _ = await router.complete_json(
                [{"role": "user", "content": prompt}],
                task=TaskType.RERANK,
                ctx=ctx,
            )
            scores = data.get("scores", [])
            if isinstance(scores, list):
                for index, chunk in enumerate(candidates):
                    if index < len(scores):
                        try:
                            chunk.rerank_score = round(float(scores[index]), 3)
                        except (TypeError, ValueError):
                            pass
        except Exception as exc:
            logger.warning("LLM rerank failed, keeping RRF order: %s", exc)
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        record_generation(trace, name="rerank_llm", model="reranker", provider="llm",
                          input_text=query[:500], output_text=str([c.rerank_score for c in candidates[:5]]),
                          latency_ms=latency_ms, task="rerank")
        return sorted(candidates, key=lambda c: c.best_score, reverse=True)[:top_k]


class HybridReranker:
    def __init__(self, llm_weight: float = 0.6, rrf_weight: float = 0.4):
        self.llm_weight = llm_weight
        self.rrf_weight = rrf_weight
        self._llm = LLMReranker()

    async def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        top_k: int,
        ctx: RunContext | None = None,
    ) -> list[RetrievedChunk]:
        candidates = chunks[:MAX_CANDIDATES]
        llm_reranked = await self._llm.rerank(query, candidates, top_k=len(candidates), ctx=ctx)
        llm_scores = {}
        for chunk in llm_reranked:
            if chunk.rerank_score is not None:
                llm_scores[chunk.chunk_id] = chunk.rerank_score

        max_rrf = max((c.fused_score for c in candidates), default=1.0) or 1.0
        for chunk in candidates:
            llm_s = llm_scores.get(chunk.chunk_id, 0.0)
            rrf_s = chunk.fused_score / max_rrf if max_rrf else 0.0
            chunk.rerank_score = round(
                self.llm_weight * llm_s + self.rrf_weight * rrf_s * 10, 3
            )
        return sorted(candidates, key=lambda c: c.best_score, reverse=True)[:top_k]


class NoopReranker:
    async def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        top_k: int,
        ctx: RunContext | None = None,
    ) -> list[RetrievedChunk]:
        return chunks[:top_k]


_reranker: Any = None


def get_reranker() -> Any:
    global _reranker
    if _reranker is None:
        _reranker = LLMReranker()
    return _reranker


def set_reranker(reranker: Any) -> None:
    global _reranker
    _reranker = reranker