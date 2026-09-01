import logging
from typing import Any

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
        candidates = chunks[:MAX_CANDIDATES]
        passages = []
        for index, chunk in enumerate(candidates, start=1):
            snippet = chunk.content[:SNIPPET_CHARS].replace("\n", " ")
            passages.append(f"[{index}] ({chunk.document_name} p.{chunk.page}): {snippet}")
        prompt = RERANK_PROMPT.format(question=query, passages="\n".join(passages))
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
