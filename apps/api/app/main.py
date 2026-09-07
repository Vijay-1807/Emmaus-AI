import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.agents.graph import get_graph
from app.api import (
    auth,
    chat,
    datasets,
    documents,
    evaluation,
    image,
    investigations,
    media,
    observability,
    telegram,
    workspaces,
)
from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.db import connect_db, close_db
from app.core.logging import configure_logging
from app.providers.registry import get_model_router
from app.rag.embeddings import get_embedding_service

configure_logging()
logger = logging.getLogger("vedax.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await connect_db()
    router = get_model_router()
    logger.info("providers: %s", list(router.providers))
    try:
        get_graph()
        logger.info("langgraph orchestrator compiled")
    except Exception as exc:
        logger.error("failed to compile graph: %s", exc)
    embedding_service = get_embedding_service()
    health = await embedding_service.health_check()
    logger.info("embedding backend: %s (ok=%s)", health.get("backend"), health.get("ok"))
    yield
    await close_db()
    logger.info("shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    # Public Swagger/OpenAPI only outside production: the API surface is
    # richer than anonymous users need, and Render's health check only
    # needs /api/health (which stays minimal-but-open below).
    is_prod = settings.environment == "production"
    app = FastAPI(
        title="Emmaus AI API",
        description="Multimodal Agentic Knowledge & Analysis Platform",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
        openapi_url=None if is_prod else "/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list if "*" not in settings.cors_origin_list else ["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    try:
        from pathlib import Path

        Path("media").mkdir(exist_ok=True)
        app.mount("/media", StaticFiles(directory="media"), name="media")
    except Exception as exc:
        logger.warning("media mount failed: %s", exc)
    prefix = settings.api_prefix
    app.include_router(auth.router, prefix=prefix)
    app.include_router(workspaces.router, prefix=prefix)
    app.include_router(documents.router, prefix=prefix)
    app.include_router(datasets.router, prefix=prefix)
    app.include_router(media.router, prefix=prefix)
    app.include_router(chat.router, prefix=prefix)
    app.include_router(investigations.router, prefix=prefix)
    app.include_router(evaluation.router, prefix=prefix)
    app.include_router(observability.router, prefix=prefix)
    app.include_router(telegram.router, prefix=prefix)
    app.include_router(image.router, prefix=prefix)

    @app.get(f"{prefix}/health")
    async def health():
        # Minimal public liveness: no secrets here (names/booleans only),
        # and the web Settings tab + status pill + Render all read this.
        from app.services.media_service import MediaService

        router = get_model_router()
        media = MediaService()
        return {
            "status": "ok",
            "environment": settings.environment,
            "providers": router.describe(),
            "storage": {
                "mode": media.mode,
                "cloudinary_configured": settings.has_cloudinary,
                "cloudinary_usable": media.cloudinary_usable,
            },
            "telegram": {"configured": bool(settings.telegram_bot_token)},
        }

    _health_cache: dict[str, Any] = {}
    _health_cache_ttl: float = 30.0

    @app.get(f"{prefix}/health/detailed")
    async def health_detailed(user: dict = Depends(get_current_user)):
        # Internal diagnostics: authenticated callers only.
        now = time.time()
        if _health_cache.get("data") and now - _health_cache.get("ts", 0) < _health_cache_ttl:
            return _health_cache["data"]
        router = get_model_router()
        embedding_service = get_embedding_service()
        embedding_health = await embedding_service.health_check()
        from app.rag.retriever import get_retriever

        retriever_health = await get_retriever().health()
        result = {
            "status": "ok",
            "providers": router.describe(),
            "embeddings": embedding_health,
            "retrieval": retriever_health,
            "storage": {"mode": settings.media_storage},
        }
        _health_cache["data"] = result
        _health_cache["ts"] = now
        return result

    return app


app = create_app()
