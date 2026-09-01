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
