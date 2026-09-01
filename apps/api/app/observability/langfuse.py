import logging
from contextlib import asynccontextmanager
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("vedax.langfuse")

_client: Any = None
_enabled: bool | None = None


def _get_client() -> Any:
    global _client, _enabled
    if _enabled is not None:
        return _client
    settings = get_settings()
    if not settings.has_langfuse:
        _enabled = False
        return None
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        _client = client
        _enabled = True
        logger.info("langfuse tracing enabled")
    except Exception as exc:
        logger.warning("langfuse unavailable, internal tracing only: %s", exc)
        _enabled = False
        _client = None
    return _client


@asynccontextmanager
async def trace_span(name: str, metadata: dict[str, Any] | None = None, run_id: str | None = None):
    client = _get_client()
    span = None
    if client is not None:
        try:
            trace_obj = client.trace(
                name=name,
                metadata=metadata or {},
                id=run_id,
            )
            span = trace_obj
        except Exception:
            span = None
    try:
        yield span
    finally:
        if span is not None and client is not None:
            try:
                client.flush()
            except Exception:
                pass


def record_generation(
    span: Any,
    *,
    name: str,
    model: str,
    provider: str,
    input_text: str,
    output_text: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: float = 0,
    task: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    if span is None:
        return
    try:
        generation = span.generation(
            name=name,
            model=model,
            model_parameters={"provider": provider, "task": task},
            input=input_text[:2000] if input_text else "",
            output=output_text[:2000] if output_text else "",
            usage={
                "input": input_tokens,
                "output": output_tokens,
            },
            metadata=metadata or {},
        )
    except Exception:
        pass


def record_event(span: Any, *, name: str, event_type: str = "default", metadata: dict[str, Any] | None = None) -> None:
    if span is None:
        return
    try:
        span.event(
            name=name,
            event_type=event_type,
            metadata=metadata or {},
        )
    except Exception:
        pass


def flush() -> None:
    client = _get_client()
    if client is not None:
        try:
            client.flush()
        except Exception:
            pass
