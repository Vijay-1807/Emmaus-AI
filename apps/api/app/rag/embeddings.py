import asyncio
import hashlib
import logging
import math
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger("vedax.embeddings")


class MockEmbedder:
    def __init__(self, dimensions: int):
        self.dimensions = dimensions

    def _embed_one(self, text: str) -> list[float]:
        tokens = text.lower().split()[:64]
        vector = [0.0] * self.dimensions
        for token in tokens:
            digest = hashlib.md5(token.encode()).digest()
            value = int.from_bytes(digest[:4], "big")
            idx = value % self.dimensions
            sign = 1.0 if value % 2 == 0 else -1.0
            vector[idx] += sign
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class OllamaEmbedder:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def embed(self, texts: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for start in range(0, len(texts), 32):
                batch = texts[start : start + 32]
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    headers=headers,
                    json={"model": self.model, "input": batch},
                )
                response.raise_for_status()
                data = response.json()["data"]
                out.extend(item["embedding"] for item in data)
        return out


class LocalEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        self.dimensions = self.model.get_sentence_embedding_dimension()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(
            lambda: [e.tolist() for e in self.model.encode(texts, show_progress_bar=False)]
        )


class EmbeddingService:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._backend: Any = None
        self._backend_name = ""

    async def _try_backend(self, backend: Any) -> bool:
        try:
            await backend.embed(["health check"])
            return True
        except Exception as exc:
            logger.info("embedding backend %s unavailable: %s", type(backend).__name__, str(exc)[:150])
            return False

    async def _resolve_backend(self) -> Any:
        if self._backend is not None:
            return self._backend
        choice = self.settings.embedding_provider
        if choice == "mock":
            self._backend = MockEmbedder(self.settings.embedding_dimensions)
            self._backend_name = "mock"
            return self._backend
        if choice == "ollama":
            self._backend = OllamaEmbedder(
                self.settings.embedding_base_url,
                self.settings.embedding_api_key_resolved,
                self.settings.embedding_model,
            )
            self._backend_name = "ollama"
            return self._backend
        if choice == "local":
            self._backend = LocalEmbedder(self.settings.local_embedding_model)
            self._backend_name = "local"
            return self._backend
        ollama = OllamaEmbedder(
            self.settings.embedding_base_url,
            self.settings.embedding_api_key_resolved,
            self.settings.embedding_model,
            timeout=10,
        )
        if await self._try_backend(ollama):
            self._backend = ollama
            self._backend_name = "ollama"
            return self._backend
        try:
            local = LocalEmbedder(self.settings.local_embedding_model)
        except ImportError:
            local = None
        if local is not None and await self._try_backend(local):
            self._backend = local
            self._backend_name = "local"
            return self._backend
        logger.warning(
            "no real embedding backend reachable, falling back to deterministic mock"
        )
        self._backend = MockEmbedder(self.settings.embedding_dimensions)
        self._backend_name = "mock"
        return self._backend

    async def health_check(self) -> dict[str, Any]:
        try:
            backend = await self._resolve_backend()
            await backend.embed(["ping"])
            return {"ok": True, "backend": self._backend_name, "model": self.settings.embedding_model}
        except Exception as exc:
            return {"ok": False, "backend": self._backend_name, "error": str(exc)[:300]}

    @property
    def backend_name(self) -> str:
        return self._backend_name

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        backend = await self._resolve_backend()
        return await backend.embed(texts)


_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
