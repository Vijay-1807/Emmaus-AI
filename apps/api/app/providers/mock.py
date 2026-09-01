import json
import time
from typing import Any, AsyncIterator

from app.providers.base import CompletionResult, RunContext, TaskType

MOCK_RESPONSES: dict[str, str] = {
    "classify": json.dumps(
        {
            "capabilities": ["rag"],
            "intent": "question",
            "needs_documents": True,
            "needs_data": False,
            "needs_vision": False,
            "reasoning": "Mock classification",
        }
    ),
    "verify": json.dumps({"sufficient": True, "reasoning": "Mock verification", "confidence": 0.9}),
    "rerank": json.dumps({"scores": [9, 5, 3, 1]}),
}


class MockProvider:
    name = "mock"

    def supports_vision(self) -> bool:
        return True

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        task: TaskType = TaskType.REASONING,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
        ctx: RunContext | None = None,
    ) -> CompletionResult:
        await time.sleep(0.01)
        key = task.value if task and task.value in MOCK_RESPONSES else "default"
        text = MOCK_RESPONSES.get(key)
        if text is None:
            text = (
                "This is a mock response from VedaX AI's offline provider. "
                "Configure OLLAMA_API_KEY or GROQ_API_KEY to enable real model inference.\n\n"
                "The full agentic pipeline (classification, retrieval, verification, citation) "
                "executed successfully in offline mode."
            )
        latency = 12.0
        if ctx:
            ctx.report(
                {
                    "provider": self.name,
                    "model": model or "mock-model",
                    "task": task.value if task else "reasoning",
                    "latency_ms": latency,
                    "input_tokens": 50,
                    "output_tokens": 60,
                    "success": True,
                    "mock": True,
                }
            )
        return CompletionResult(
            text=text,
            provider=self.name,
            model=model or "mock-model",
            task=task.value if task else "reasoning",
            latency_ms=latency,
            input_tokens=50,
            output_tokens=60,
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        task: TaskType = TaskType.REASONING,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        ctx: RunContext | None = None,
    ) -> AsyncIterator[str]:
        result = await self.complete(
            messages, task=task, model=model, temperature=temperature, ctx=ctx
        )
        for word in result.text.split(" "):
            yield word + " "
