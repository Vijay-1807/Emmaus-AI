import logging
from contextlib import contextmanager
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
        from langfuse import get_client

        client = get_client()
        _client = client
        _enabled = True
        logger.info("langfuse tracing enabled")
    except Exception as exc:
        logger.warning("langfuse unavailable, internal tracing only: %s", exc)
        _enabled = False
        _client = None
    return _client


@contextmanager
def trace(name: str, **metadata: Any):
    client = _get_client()
    span = None
    if client is not None:
        try:
            span = client.start_span(name=name, metadata=metadata)
        except Exception:
            span = None
    try:
        yield span
    finally:
        if span is not None:
            try:
                span.end()
            except Exception:
                pass


def record_generation(span: Any, *, name: str, model: str, input_text: str, output_text: str, **kwargs: Any) -> None:
    if span is None:
        return
    try:
        child = span.start_generation(name=name, model=model, input=input_text, output=output_text, **kwargs)
        child.end()
    except Exception:
        pass
