import asyncio
import hashlib
import logging
import math
from dataclasses import dataclass
from typing import Any

import google.generativeai as genai
import httpx

from app.core.config import get_settings

logger = logging.getLogger("vedax.embeddings")


@dataclass(frozen=True)
class EmbeddingDescriptor:
    backend: str
    model: str
    dimensions: int
    provider: str


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


class GeminiEmbedder:
    def __init__(
        self, api_key: str, model: str = "gemini-embedding-001", timeout: float = 60
    ):
        genai.configure(api_key=api_key)
        self.model = model
        self.timeout = timeout

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            result = await asyncio.to_thread(
                lambda: genai.embed_content(
                    model=self.model,
                    content=text,
                    task_type="retrieval_document",
                )
            )
            out.append(result["embedding"])
        return out


class EmbeddingService:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._backend: Any = None
        self._backend_name = ""
        self._descriptor: EmbeddingDescriptor | None = None

    async def _try_backend(self, backend: Any, name: str) -> bool:
        try:
            vecs = await backend.embed(["health check"])
            if not vecs or not vecs[0]:
                return False
            dim = len(vecs[0])
            expected = self._expected_dimensions()
            if dim != expected:
                logger.error(
                    "Embedding backend %s returned %d dimensions, expected %d",
                    name,
                    dim,
                    expected,
                )
                return False
            return True
        except Exception as exc:
            logger.info("embedding backend %s unavailable: %s", name, str(exc)[:150])
            return False

    def _expected_dimensions(self) -> int:
        if self.settings.embedding_provider == "gemini":
            return self.settings.gemini_embedding_dimensions
        return self.settings.embedding_dimensions

    async def _resolve_backend(self) -> Any:
        if self._backend is not None:
            return self._backend

        choice = self.settings.embedding_provider
        is_prod = self.settings.environment == "production"

        if choice == "gemini" or (choice == "auto" and self.settings.has_gemini):
            gemini = GeminiEmbedder(
                self.settings.gemini_api_key,
                self.settings.gemini_embedding_model,
            )
            if await self._try_backend(gemini, "gemini"):
                self._backend = gemini
                self._backend_name = "gemini"
                self._descriptor = EmbeddingDescriptor(
                    backend="gemini",
                    model=self.settings.gemini_embedding_model,
                    dimensions=self.settings.gemini_embedding_dimensions,
                    provider="google",
                )
                return self._backend
            if is_prod:
                raise RuntimeError(
                    "Gemini Embedding 2 unavailable and no fallback allowed in production"
                )

        if choice == "ollama" or (choice == "auto" and self.settings.has_ollama):
            ollama = OllamaEmbedder(
                self.settings.embedding_base_url,
                self.settings.embedding_api_key or self.settings.ollama_api_key,
                self.settings.embedding_model,
                timeout=10,
            )
            if await self._try_backend(ollama, "ollama"):
                self._backend = ollama
                self._backend_name = "ollama"
                self._descriptor = EmbeddingDescriptor(
                    backend="ollama",
                    model=self.settings.embedding_model,
                    dimensions=self.settings.embedding_dimensions,
                    provider="ollama",
                )
                return self._backend
            if is_prod and choice == "ollama":
                raise RuntimeError(
                    "Ollama embeddings unavailable and no fallback allowed in production"
                )

        try:
            local = LocalEmbedder(self.settings.local_embedding_model)
        except ImportError:
            local = None
        if local is not None and await self._try_backend(local, "local"):
            self._backend = local
            self._backend_name = "local"
            self._descriptor = EmbeddingDescriptor(
                backend="local",
                model=self.settings.local_embedding_model,
                dimensions=local.dimensions,
                provider="sentence-transformers",
            )
            return self._backend

        if is_prod:
            raise RuntimeError(
                "No embedding backend available in production. "
                "Configure GEMINI_API_KEY or OLLAMA_API_KEY."
            )

        logger.warning(
            "no real embedding backend reachable, falling back to deterministic mock"
        )
        self._backend = MockEmbedder(self._expected_dimensions())
        self._backend_name = "mock"
        self._descriptor = EmbeddingDescriptor(
            backend="mock",
            model="mock",
            dimensions=self._expected_dimensions(),
            provider="mock",
        )
        return self._backend

    async def health_check(self) -> dict[str, Any]:
        try:
            backend = await self._resolve_backend()
            await backend.embed(["ping"])
            desc = self.descriptor
            return {
                "ok": True,
                "backend": self._backend_name,
                "model": desc.model if desc else self.settings.embedding_model,
                "dimensions": desc.dimensions if desc else self._expected_dimensions(),
                "provider": desc.provider if desc else "unknown",
            }
        except Exception as exc:
            return {"ok": False, "backend": self._backend_name, "error": str(exc)[:300]}

    @property
    def backend_name(self) -> str:
        return self._backend_name

    @property
    def descriptor(self) -> EmbeddingDescriptor | None:
        return self._descriptor

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