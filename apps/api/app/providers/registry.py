import logging
from typing import Any

from app.core.config import get_settings
from app.providers.base import (
    CompletionResult,
    LLMProvider,
    RunContext,
    TaskType,
    extract_json,
    with_retries,
)
from app.providers.cerebras import CerebrasProvider
from app.providers.groq import GroqProvider
from app.providers.mock import MockProvider
from app.providers.ollama import OllamaProvider

logger = logging.getLogger("vedax.router")

COST_PER_MTOK: dict[tuple[str, str], tuple[float, float]] = {
    ("groq", "llama-3.3-70b-versatile"): (0.59, 0.79),
    ("groq", "llama-3.1-8b-instant"): (0.05, 0.08),
    ("cerebras", "llama-3.3-70b"): (0.85, 1.20),
    ("ollama", "gpt-oss:120b"): (0.5, 1.5),
}


def estimate_cost_usd(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    rates = COST_PER_MTOK.get((provider, model), (0.0, 0.0))
    return round(
        (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000, 6
    )


class ModelRouter:
    def __init__(self, providers: dict[str, LLMProvider], settings):
        self.providers = providers
        self.settings = settings

    def _chain(self, task: TaskType) -> list[tuple[LLMProvider, str]]:
        s = self.settings
        chain: list[tuple[LLMProvider, str]] = []
        if task == TaskType.VISION:
            if "ollama" in self.providers:
                chain.append((self.providers["ollama"], s.ollama_vision_model))
            chain.append((self.providers["mock"], "mock-vision"))
            return chain
        if task in (TaskType.CLASSIFY, TaskType.REWRITE, TaskType.RERANK, TaskType.VERIFY,
                    TaskType.EXTRACTION, TaskType.EVALUATION):
            if "groq" in self.providers:
                chain.append((self.providers["groq"], s.groq_fast_model))
            if "ollama" in self.providers:
                chain.append((self.providers["ollama"], s.ollama_chat_model))
            if "cerebras" in self.providers:
                chain.append((self.providers["cerebras"], s.cerebras_chat_model))
            chain.append((self.providers["mock"], "mock-fast"))
            return chain
        if task == TaskType.REASONING:
            if "ollama" in self.providers:
                chain.append((self.providers["ollama"], s.ollama_chat_model))
            if "groq" in self.providers:
                chain.append((self.providers["groq"], s.groq_chat_model))
            if "cerebras" in self.providers:
                chain.append((self.providers["cerebras"], s.cerebras_chat_model))
            chain.append((self.providers["mock"], "mock-reasoning"))
            return chain
        chain.append((self.providers["mock"], "mock-default"))
        return chain

    def primary_provider_name(self, task: TaskType) -> str:
        chain = self._chain(task)
        return chain[0][0].name if chain else "none"

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        task: TaskType,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
        ctx: RunContext | None = None,
    ) -> CompletionResult:
        errors: list[str] = []
        chain = self._chain(task)
        for index, (provider, model) in enumerate(chain):
            try:
                result = await provider.complete(
                    messages,
                    task=task,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    ctx=ctx,
                )
                if index > 0:
                    result.fallback_used = True
                    logger.warning(
                        "task %s fell back to %s/%s",
                        task.value,
                        provider.name,
                        model,
                    )
                return result
            except Exception as exc:
                errors.append(f"{provider.name}/{model}: {exc}")
                logger.error("provider %s/%s failed for task %s: %s", provider.name, model, task.value, exc)
        raise RuntimeError(f"all providers failed for task {task.value}: {'; '.join(errors)}")

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        task: TaskType = TaskType.REASONING,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        ctx: RunContext | None = None,
    ):
        chain = self._chain(task)
        errors: list[str] = []
        for index, (provider, model) in enumerate(chain):
            try:
                iterator = provider.stream(
                    messages,
                    task=task,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    ctx=ctx,
                )
                first_chunk = await iterator.__anext__()
            except StopAsyncIteration:
                continue
            except Exception as exc:
                errors.append(f"{provider.name}/{model}: {exc}")
                logger.error("stream provider %s failed: %s", provider.name, exc)
                continue

            async def _stream(current, m):
                yield first_chunk
                async for piece in current:
                    yield piece

            return _stream(iterator, model)
        raise RuntimeError(f"all stream providers failed: {'; '.join(errors)}")

    async def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        task: TaskType,
        schema: type | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        ctx: RunContext | None = None,
    ):
        result = await with_retries(
            lambda: self.complete(
                messages,
                task=task,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=True,
                ctx=ctx,
            )
        )
        data = extract_json(result.text)
        if schema is not None:
            data = schema.model_validate(data)
        return data, result

    def describe(self) -> dict[str, Any]:
        return {
            "providers": {
                name: {"available": True, "default_model": getattr(p, "default_model", "n/a")}
                for name, p in self.providers.items()
            },
            "routing": {
                "reasoning": self.primary_provider_name(TaskType.REASONING),
                "fast_tasks": self.primary_provider_name(TaskType.CLASSIFY),
                "vision": self.primary_provider_name(TaskType.VISION),
            },
        }


_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    global _router
    if _router is None:
        settings = get_settings()
        providers: dict[str, LLMProvider] = {}
        if settings.has_ollama:
            providers["ollama"] = OllamaProvider(
                settings.ollama_api_key,
                settings.ollama_base_url,
                settings.ollama_chat_model,
                settings.ollama_vision_model,
            )
        if settings.has_groq:
            providers["groq"] = GroqProvider(
                settings.groq_api_key,
                settings.groq_base_url,
                settings.groq_chat_model,
                settings.groq_fast_model,
            )
        if settings.has_cerebras:
            providers["cerebras"] = CerebrasProvider(
                settings.cerebras_api_key,
                settings.cerebras_base_url,
                settings.cerebras_chat_model,
            )
        providers["mock"] = MockProvider()
        _router = ModelRouter(providers, settings)
        logger.info("model router initialized: %s", list(providers))
    return _router
