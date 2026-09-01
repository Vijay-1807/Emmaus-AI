import contextvars
from typing import Any, Callable

from app.providers.base import RunContext

_emitter: contextvars.ContextVar[Callable[[dict[str, Any]], None] | None] = contextvars.ContextVar(
    "vedax_emitter", default=None
)
_run_ctx: contextvars.ContextVar[RunContext | None] = contextvars.ContextVar(
    "vedax_run_ctx", default=None
)


def set_emitter(emitter: Callable[[dict[str, Any]], None] | None) -> contextvars.Token:
    return _emitter.set(emitter)


def reset_emitter(token: contextvars.Token) -> None:
    _emitter.reset(token)


def emit(event: dict[str, Any]) -> None:
    emitter = _emitter.get()
    if emitter is not None:
        try:
            emitter(event)
        except Exception:
            pass


def set_run_ctx(ctx: RunContext | None) -> contextvars.Token:
    return _run_ctx.set(ctx)


def reset_run_ctx(token: contextvars.Token) -> None:
    _run_ctx.reset(token)


def get_run_ctx() -> RunContext:
    return _run_ctx.get() or RunContext()
