def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int = 5) -> float:
    if not relevant_ids:
        return 0.0
    top = set(retrieved_ids[:k])
    hits = len(top & set(relevant_ids))
    return hits / len(set(relevant_ids))


def mrr(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    relevant = set(relevant_ids)
    for rank, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int = 5) -> float:
    import math

    relevant = set(relevant_ids)
    dcg = 0.0
    for rank, chunk_id in enumerate(retrieved_ids[:k], start=1):
        if chunk_id in relevant:
            dcg += 1.0 / math.log2(rank + 1)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


GRADED_PROMPT = """You are a strict evaluator for a RAG system.

Question: {question}
Expected answer: {expected}
System answer: {actual}

Respond ONLY with JSON:
{{"correctness": <0.0-1.0>, "faithfulness": <0.0-1.0>, "reasoning": "<one sentence>"}}
- correctness: does the answer give the same information as expected?
- faithfulness: is the answer supported by its citations/evidence (no hallucination)?"""


async def grade_answer(question: str, expected: str, actual: str, citations: list, ctx) -> dict:
    from app.providers.base import TaskType
    from app.providers.registry import get_model_router

    citation_note = f"({len(citations)} citations attached)" if citations is not None else "(no citations)"
    prompt = GRADED_PROMPT.format(
        question=question, expected=expected, actual=f"{actual[:2000]}\n{citation_note}"
    )
    try:
        router = get_model_router()
        data, _ = await router.complete_json(
            [{"role": "user", "content": prompt}],
            task=TaskType.EVALUATION,
            ctx=ctx,
        )
        return {
            "correctness": max(0.0, min(1.0, float(data.get("correctness", 0.0)))),
            "faithfulness": max(0.0, min(1.0, float(data.get("faithfulness", 0.0)))),
            "reasoning": str(data.get("reasoning", ""))[:300],
        }
    except Exception:
        expected_lower = expected.lower().strip()
        actual_lower = actual.lower()
        overlap = sum(1 for token in expected_lower.split() if len(token) > 3 and token in actual_lower)
        total = max(1, len([t for t in expected_lower.split() if len(t) > 3]))
        return {
            "correctness": round(overlap / total, 3),
            "faithfulness": 0.5,
            "reasoning": "graded by token overlap (LLM grader unavailable)",
        }


def citation_accuracy(answer: str, citations: list, expected_sources: list[str] | None) -> float:
    if not expected_sources:
        return 1.0 if citations else 0.0
    cited_names = {c.get("document_name", "") for c in citations}
    hits = sum(1 for source in expected_sources if any(source in name or name in source for name in cited_names))
    return hits / len(expected_sources)
