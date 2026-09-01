import logging
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from app.providers.base import CompletionResult, RunContext, TaskType, now_ms, with_retries

logger = logging.getLogger("vedax.providers.openai_compat")


class OpenAICompatProvider:
    def __init__(self, name: str, api_key: str, base_url: str, default_model: str):
        self.name = name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self._client = AsyncOpenAI(api_key=api_key, base_url=self.base_url, max_retries=2, timeout=120)

    def supports_vision(self) -> bool:
        return False

    def _usage(self, response) -> tuple[int, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0, 0
        return getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        task: TaskType,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
        ctx: RunContext | None = None,
    ) -> CompletionResult:
        model = model or self.default_model
        extra: dict[str, Any] = {}
        if json_mode:
            extra["response_format"] = {"type": "json_object"}

        async def _call() -> Any:
            return await self._client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **extra,
            )

        started = now_ms()
        try:
            response = await with_retries(_call)
        except Exception as exc:
            latency = now_ms() - started
            if ctx:
                ctx.report(
                    {
                        "provider": self.name,
                        "model": model,
                        "task": task.value,
                        "latency_ms": latency,
                        "success": False,
                        "error": str(exc)[:500],
                    }
                )
            raise
        latency = now_ms() - started
        text = response.choices[0].message.content or ""
        input_tokens, output_tokens = self._usage(response)
        if ctx:
            ctx.report(
                {
                    "provider": self.name,
                    "model": model,
                    "task": task.value,
                    "latency_ms": latency,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "success": True,
                }
            )
        return CompletionResult(
            text=text,
            provider=self.name,
            model=model,
            task=task.value,
            latency_ms=latency,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
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
        model = model or self.default_model
        started = now_ms()
        collected: list[str] = []
        stream = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        try:
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    piece = chunk.choices[0].delta.content
                    collected.append(piece)
                    yield piece
                if getattr(chunk, "usage", None):
                    usage = chunk.usage
                    if ctx:
                        ctx.report(
                            {
                                "provider": self.name,
                                "model": model,
                                "task": task.value,
                                "latency_ms": now_ms() - started,
                                "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                                "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
                                "success": True,
                                "stream": True,
                            }
                        )
        except Exception:
            if ctx:
                ctx.report(
                    {
                        "provider": self.name,
                        "model": model,
                        "task": task.value,
                        "latency_ms": now_ms() - started,
                        "success": False,
                    }
                )
            raise
