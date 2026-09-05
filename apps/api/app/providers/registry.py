import asyncio
import logging
import time
from typing import Any

from app.core.config import get_settings
from app.observability.langfuse import _get_client as _get_langfuse
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

# Per-provider concurrency caps for non-streaming calls. Bursts of parallel
# fast-model calls (classify/rewrite/rerank/verify across concurrent
# investigations) otherwise stampede free-tier TPM limits into 429 storms.
_SEMAPHORES: dict[str, asyncio.Semaphore] = {}


def _semaphore_for(provider_name: str, limit: int) -> asyncio.Semaphore:
    key = f"{provider_name}:{limit}"
    sem = _SEMAPHORES.get(key)
    if sem is None:
        sem = asyncio.Semaphore(max(1, limit))
        _SEMAPHORES[key] = sem
    return sem

COST_PER_MTOK: dict[tuple[str, str], tuple[float, float]] = {
    ("groq", "openai/gpt-oss-120b"): (0.15, 0.60),
    ("groq", "openai/gpt-oss-20b"): (0.075, 0.30),
    ("groq", "qwen/qwen3.6-27b"): (0.60, 3.00),
    ("groq", "qwen/qwen3.8-27b"): (0.80, 4.00),
    ("ollama", "gpt-oss:120b"): (0.0, 0.0),
    ("ollama", "gemma4:31b"): (0.0, 0.0),
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
            # Groq's scout model is OpenAI-compatible and reliable for image_url
            # payloads; Ollama Cloud stays as fallback, then mock.
            if "groq" in self.providers:
                chain.append((self.providers["groq"], s.groq_vision_model))
            if "ollama" in self.providers:
                chain.append((self.providers["ollama"], s.ollama_vision_model))
            if "mock" in self.providers:
                chain.append((self.providers["mock"], "mock-vision"))
            return chain

        if task in (TaskType.CLASSIFY, TaskType.REWRITE, TaskType.RERANK, TaskType.VERIFY,
                    TaskType.EXTRACTION, TaskType.EVALUATION):
            if "groq" in self.providers:
                chain.append((self.providers["groq"], s.groq_fast_model))
            if "ollama" in self.providers:
                chain.append((self.providers["ollama"], s.ollama_chat_model))
            if "mock" in self.providers:
                chain.append((self.providers["mock"], "mock-fast"))
            return chain

        if task == TaskType.REASONING:
            if "groq" in self.providers:
                chain.append((self.providers["groq"], s.groq_chat_model))
            if "ollama" in self.providers:
                chain.append((self.providers["ollama"], s.ollama_chat_model))
            if "mock" in self.providers:
                chain.append((self.providers["mock"], "mock-reasoning"))
            return chain

        if "mock" in self.providers:
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
        lf_client = _get_langfuse()
        for index, (provider, model) in enumerate(chain):
            try:
                started = time.perf_counter()
                try:
                    limit = int(getattr(self.settings, "provider_max_concurrency", 3) or 3)
                except (TypeError, ValueError):
                    limit = 3
                async with _semaphore_for(provider.name, limit):
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
                if lf_client is not None and ctx is not None:
                    try:
                        input_preview = str(messages[-1].get("content", ""))[:500] if messages else ""
                        lf_client.span(
                            name=f"llm:{task.value}",
                            input=input_preview,
                            output=result.text[:500],
                            model=model,
                            metadata={
                                "provider": provider.name,
                                "task": task.value,
                                "input_tokens": result.input_tokens,
                                "output_tokens": result.output_tokens,
                                "latency_ms": result.latency_ms,
                                "fallback_used": result.fallback_used,
                            },
                        )
                    except Exception:
                        pass
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

            yield first_chunk
            async for piece in iterator:
                yield piece
            return
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
        def _info(p: LLMProvider) -> dict[str, Any]:
            info: dict[str, Any] = {
                "available": True,
                "default_model": getattr(p, "default_model", "n/a"),
            }
            for attr in ("fast_model", "vision_model"):
                if hasattr(p, attr):
                    info[attr] = getattr(p, attr)
            return info

        return {
            "providers": {name: _info(p) for name, p in self.providers.items()},
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
        # Cerebras removed - account has no quota (402). Re-enable when billing is fixed.
        # if settings.has_cerebras:
        #     providers["cerebras"] = CerebrasProvider(
        #         settings.cerebras_api_key,
        #         settings.cerebras_base_url,
        #         settings.cerebras_chat_model,
        #         settings.cerebras_vision_model,
        #     )
        if settings.has_groq:
            providers["groq"] = GroqProvider(
                settings.groq_api_key,
                settings.groq_base_url,
                settings.groq_chat_model,
                settings.groq_fast_model,
                settings.groq_vision_model,
            )
        if settings.has_ollama:
            providers["ollama"] = OllamaProvider(
                settings.ollama_api_key,
                settings.ollama_base_url,
                settings.ollama_chat_model,
                settings.ollama_vision_model,
            )
        providers["mock"] = MockProvider()
        _router = ModelRouter(providers, settings)
        logger.info("model router initialized: %s", list(providers))
    return _router
