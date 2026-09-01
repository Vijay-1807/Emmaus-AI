from app.providers.base import RunContext, TaskType
from app.providers.registry import get_model_router

REWRITE_PROMPT = """Rewrite the user's question into a standalone, search-optimized query for a document retrieval system.

Rules:
- Resolve pronouns using the conversation history.
- Keep all key entities, numbers and constraints.
- Expand abbreviations only if unambiguous.
- Output ONLY the rewritten query text, nothing else.

Conversation history (may be empty):
{history}

Question: {question}

Rewritten query:"""

MULTI_QUERY_PROMPT = """Generate 3 alternative search queries that would find relevant documents for answering this question.

Original question: {question}

Context: {context}

Rules:
- Each query should approach the question from a different angle.
- Use different terminology and synonyms.
- Keep queries specific and factual.
- Output ONLY the 3 queries, one per line, nothing else."""


async def rewrite_query(
    question: str,
    history: list[dict] | None = None,
    ctx: RunContext | None = None,
) -> str:
    history_text = ""
    if history:
        lines = []
        for message in history[-6:]:
            role = "User" if message.get("role") == "user" else "Assistant"
            lines.append(f"{role}: {str(message.get('content', ''))[:300]}")
        history_text = "\n".join(lines)
    prompt = REWRITE_PROMPT.format(question=question, history=history_text or "(empty)")
    try:
        router = get_model_router()
        result = await router.complete(
            [{"role": "user", "content": prompt}],
            task=TaskType.REWRITE,
            temperature=0.0,
            max_tokens=200,
            ctx=ctx,
        )
        rewritten = result.text.strip().strip('"').strip()
        return rewritten or question
    except Exception:
        return question


async def generate_multi_queries(
    question: str,
    context: str = "",
    ctx: RunContext | None = None,
    num_queries: int = 3,
) -> list[str]:
    prompt = MULTI_QUERY_PROMPT.format(
        question=question, context=context or "(no additional context)"
    )
    try:
        router = get_model_router()
        result = await router.complete(
            [{"role": "user", "content": prompt}],
            task=TaskType.REWRITE,
            temperature=0.3,
            max_tokens=300,
            ctx=ctx,
        )
        lines = [line.strip() for line in result.text.strip().split("\n") if line.strip()]
        queries = []
        for line in lines[:num_queries]:
            cleaned = line.lstrip("0123456789.-) ").strip()
            if cleaned and cleaned.lower() != question.lower():
                queries.append(cleaned)
        return queries
    except Exception:
        return []
