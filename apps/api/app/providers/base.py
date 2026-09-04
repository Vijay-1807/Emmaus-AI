import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Protocol

logger = logging.getLogger("vedax.providers")


class TaskType(str, Enum):
    REASONING = "reasoning"
    CLASSIFY = "classify"
    REWRITE = "rewrite"
    RERANK = "rerank"
    VERIFY = "verify"
    VISION = "vision"
    EXTRACTION = "extraction"
    EVALUATION = "evaluation"


@dataclass
class CompletionResult:
    text: str
    provider: str
    model: str
    task: str
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    fallback_used: bool = False
    error: str | None = None


@dataclass
class RunContext:
    investigation_id: str | None = None
    conversation_id: str | None = None
    workspace_id: str | None = None
    trace_id: str = ""
    langfuse_trace: Any = None
    on_run: Callable[[dict[str, Any]], None] | None = None
    notes: dict[str, Any] = field(default_factory=dict)

    def report(self, run: dict[str, Any]) -> None:
        if self.on_run:
            run = {**run, **{"investigation_id": self.investigation_id, "trace_id": self.trace_id}}
            try:
                self.on_run(run)
            except Exception:
                logger.debug("run reporter failed", exc_info=True)


class LLMProvider(Protocol):
    name: str

    def supports_vision(self) -> bool: ...

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        task: TaskType,
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
        ctx: RunContext | None = None,
    ) -> CompletionResult: ...

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        task: TaskType,
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        ctx: RunContext | None = None,
    ) -> AsyncIterator[str]: ...


JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def extract_json(text: str) -> Any:
    cleaned = text.strip()
    match = JSON_BLOCK_RE.search(cleaned)
    if match:
        cleaned = match.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError("no valid JSON found in model output")


def _retry_after_seconds(exc: Exception, default: float) -> float:
    """Honor Groq/rate-limit 'try again in Xs' hints instead of hammering."""
    import random
    import re

    text = str(exc)
    match = re.search(r"try again in ([\d.]+)s", text)
    if match:
        try:
            return min(float(match.group(1)) + random.uniform(0.2, 0.8), 30.0)
        except ValueError:
            pass
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        for key in ("retry-after", "retry-after-ms", "ratelimit-reset"):
            value = headers.get(key)
            if value is not None:
                try:
                    seconds = float(value) / 1000.0 if key == "retry-after-ms" else float(value)
                    return min(max(seconds, 0.5), 30.0)
                except (TypeError, ValueError):
                    continue
    return default


async def with_retries(fn, *, attempts: int = 3, base_delay: float = 0.8) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await fn()
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                delay = max(base_delay * 2 ** (attempt - 1), _retry_after_seconds(exc, 0.0))
                logger.warning(
                    "provider attempt %s/%s failed: %s (retrying in %.1fs)",
                    attempt, attempts, exc, delay,
                )
                await asyncio.sleep(delay)
    raise last_error


def now_ms() -> float:
    return round(time.perf_counter() * 1000, 2)
