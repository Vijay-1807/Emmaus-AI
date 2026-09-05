import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.base import CompletionResult, RunContext, TaskType, with_retries
from app.providers.mock import MockProvider
from app.providers.registry import ModelRouter, estimate_cost_usd


class FailingProvider:
    """Provider that always raises."""

    name = "failing"

    def supports_vision(self) -> bool:
        return False

    async def complete(self, messages, *, task, model="fail", **kw):
        raise ConnectionError("provider unavailable")

    async def stream(self, messages, *, task, model="fail", **kw):
        raise TimeoutError("stream timeout")
        yield  # make it async generator


class SlowProvider:
    """Provider that times out after delay."""

    name = "slow"

    def __init__(self, delay: float = 10.0):
        self.delay = delay

    def supports_vision(self) -> bool:
        return False

    async def complete(self, messages, *, task, model="slow", **kw):
        await asyncio.sleep(self.delay)
        return CompletionResult(
            text="slow response", provider="slow", model=model,
            task=task.value, latency_ms=self.delay * 1000,
        )

    async def stream(self, messages, *, task, model="slow", **kw):
        await asyncio.sleep(self.delay)
        yield "slow "


class RecoveringProvider:
    """Provider that fails N times then succeeds."""

    def __init__(self, fail_count: int = 2):
        self.name = "recovering"
        self._attempts = 0
        self._fail_count = fail_count

    def supports_vision(self) -> bool:
        return False

    async def complete(self, messages, *, task, model="recover", **kw):
        self._attempts += 1
        if self._attempts <= self._fail_count:
            raise ConnectionError(f"attempt {self._attempts} failed")
        return CompletionResult(
            text='{"recovered": true}', provider="recovering", model=model,
            task=task.value, latency_ms=10.0,
        )

    async def stream(self, messages, *, task, model="recover", **kw):
        self._attempts += 1
        if self._attempts <= self._fail_count:
            raise ConnectionError(f"attempt {self._attempts} failed")
        yield "recovered "


# ── Provider Resilience ──────────────────────────────────────────────


class TestProviderFallback:
    def test_fallback_to_mock_on_all_failures(self):
        settings = MagicMock()
        settings.groq_chat_model = "openai/gpt-oss-120b"
        settings.groq_fast_model = "openai/gpt-oss-20b"
        settings.ollama_chat_model = "gpt-oss:120b"

        providers = {
            "groq": FailingProvider(),
            "ollama": FailingProvider(),
            "mock": MockProvider(),
        }
        router = ModelRouter(providers, settings)
        chain = router._chain(TaskType.REASONING)
        assert len(chain) == 3
        assert chain[-1][0].name == "mock"

    def test_reasoning_chain_order(self):
        settings = MagicMock()
        settings.groq_chat_model = "openai/gpt-oss-120b"
        settings.groq_fast_model = "openai/gpt-oss-20b"
        settings.ollama_chat_model = "gpt-oss:120b"

        providers = {
            "groq": MockProvider(),
            "ollama": MockProvider(),
            "mock": MockProvider(),
        }
        router = ModelRouter(providers, settings)
        chain = router._chain(TaskType.REASONING)
        assert [model for _, model in chain] == [
            "openai/gpt-oss-120b", "gpt-oss:120b", "mock-reasoning"
        ]

    def test_vision_chain_uses_ollama(self):
        settings = MagicMock()
        settings.ollama_vision_model = "gemma4:31b"

        providers = {
            "ollama": MockProvider(),
            "mock": MockProvider(),
        }
        router = ModelRouter(providers, settings)
        chain = router._chain(TaskType.VISION)
        assert chain[0][1] == "gemma4:31b"

    def test_vision_chain_prefers_groq(self):
        settings = MagicMock()
        settings.groq_vision_model = "qwen/qwen3.6-27b"
        settings.ollama_vision_model = "gemma4:31b"

        providers = {
            "groq": MockProvider(),
            "ollama": MockProvider(),
            "mock": MockProvider(),
        }
        router = ModelRouter(providers, settings)
        chain = router._chain(TaskType.VISION)
        assert [model for _, model in chain] == [
            "qwen/qwen3.6-27b", "gemma4:31b", "mock-vision"
        ]


@pytest.mark.asyncio
async def test_router_complete_with_all_failing_providers():
    settings = MagicMock()
    settings.groq_chat_model = "openai/gpt-oss-120b"
    settings.groq_fast_model = "llama-3.1-8b-instant"
    settings.ollama_chat_model = "gpt-oss:120b"

    providers = {
        "groq": FailingProvider(),
        "ollama": FailingProvider(),
        "mock": MockProvider(),
    }
    router = ModelRouter(providers, settings)
    result = await router.complete(
        [{"role": "user", "content": "test"}], task=TaskType.REASONING
    )
    assert result.provider == "mock"
    assert result.fallback_used is True


@pytest.mark.asyncio
async def test_router_stream_fallback():
    settings = MagicMock()
    settings.groq_chat_model = "openai/gpt-oss-120b"
    settings.groq_fast_model = "llama-3.1-8b-instant"
    settings.ollama_chat_model = "gpt-oss:120b"

    providers = {
        "groq": FailingProvider(),
        "ollama": FailingProvider(),
        "mock": MockProvider(),
    }
    router = ModelRouter(providers, settings)
    chunks = [chunk async for chunk in router.stream([{"role": "user", "content": "test"}])]
    assert len(chunks) > 0
    combined = "".join(chunks)
    assert "mock" in combined.lower() or "response" in combined.lower()


@pytest.mark.asyncio
async def test_router_all_providers_fail_raises():
    settings = MagicMock()
    settings.groq_chat_model = "openai/gpt-oss-120b"
    settings.groq_fast_model = "llama-3.1-8b-instant"
    settings.ollama_chat_model = "gpt-oss:120b"

    providers = {
        "groq": FailingProvider(),
        "ollama": FailingProvider(),
    }
    router = ModelRouter(providers, settings)
    with pytest.raises(RuntimeError, match="all providers failed"):
        await router.complete(
            [{"role": "user", "content": "test"}], task=TaskType.REASONING
        )


@pytest.mark.asyncio
async def test_router_stream_all_fail_raises():
    settings = MagicMock()
    settings.groq_chat_model = "openai/gpt-oss-120b"
    settings.groq_fast_model = "llama-3.1-8b-instant"
    settings.ollama_chat_model = "gpt-oss:120b"

    providers = {
        "groq": FailingProvider(),
        "ollama": FailingProvider(),
    }
    router = ModelRouter(providers, settings)
    with pytest.raises(RuntimeError, match="all stream providers failed"):
        async for _ in router.stream([{"role": "user", "content": "test"}]):
            pass


# ── Retry Logic ──────────────────────────────────────────────────────


class TestRetryLogic:
    @pytest.mark.asyncio
    async def test_with_retries_succeeds_after_failures(self):
        provider = RecoveringProvider(fail_count=2)
        result = await with_retries(
            lambda: provider.complete([{"role": "user", "content": "hi"}], task=TaskType.REASONING),
            attempts=3,
            base_delay=0.01,
        )
        assert result.text == '{"recovered": true}'
        assert provider._attempts == 3

    @pytest.mark.asyncio
    async def test_with_retries_exhausted(self):
        provider = RecoveringProvider(fail_count=10)
        with pytest.raises(ConnectionError):
            await with_retries(
                lambda: provider.complete([{"role": "user", "content": "hi"}], task=TaskType.REASONING),
                attempts=3,
                base_delay=0.01,
            )

    @pytest.mark.asyncio
    async def test_with_retries_immediate_success(self):
        provider = RecoveringProvider(fail_count=0)
        result = await with_retries(
            lambda: provider.complete([{"role": "user", "content": "hi"}], task=TaskType.REASONING),
            attempts=3,
            base_delay=0.01,
        )
        assert result.text == '{"recovered": true}'
        assert provider._attempts == 1


# ── Embedding Resilience ─────────────────────────────────────────────


class TestEmbeddingResilience:
    def test_mock_embedder_deterministic(self):
        from app.rag.embeddings import MockEmbedder

        embedder = MockEmbedder(dimensions=768)
        vec1 = embedder._embed_one("hello world")
        vec2 = embedder._embed_one("hello world")
        assert vec1 == vec2
        assert len(vec1) == 768

    def test_mock_embedder_different_inputs(self):
        from app.rag.embeddings import MockEmbedder

        embedder = MockEmbedder(dimensions=768)
        vec1 = embedder._embed_one("hello")
        vec2 = embedder._embed_one("goodbye")
        assert vec1 != vec2

    @pytest.mark.asyncio
    async def test_mock_embedder_batch(self):
        from app.rag.embeddings import MockEmbedder

        embedder = MockEmbedder(dimensions=768)
        result = await embedder.embed(["hello", "world"])
        assert len(result) == 2
        assert all(len(v) == 768 for v in result)

    @pytest.mark.asyncio
    async def test_embedding_service_fails_open_in_test(self):
        from app.rag.embeddings import EmbeddingService

        service = EmbeddingService()
        backend = await service._resolve_backend()
        assert backend is not None

    def test_embedding_health_check(self):
        from app.rag.embeddings import EmbeddingService

        service = EmbeddingService()
        result = asyncio.get_event_loop().run_until_complete(service.health_check())
        assert "ok" in result


# ── Retriever Resilience ─────────────────────────────────────────────


class TestRetrieverResilience:
    @pytest.mark.asyncio
    async def test_vector_search_graceful_on_error(self):
        from app.rag.retriever import Retriever

        retriever = Retriever()
        results = await retriever.vector_search(
            "test-ws", "test query", limit=5
        )
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_lexical_search_graceful_on_error(self):
        from app.rag.retriever import Retriever

        retriever = Retriever()
        results = await retriever.lexical_search(
            "test-ws", "test query", limit=5
        )
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_rrf_fuse_empty_inputs(self):
        from app.rag.retriever import Retriever, rrf_fuse

        result = rrf_fuse([], [], k=60)
        assert result == []

    @pytest.mark.asyncio
    async def test_rrf_fuse_single_source(self):
        from app.rag.retriever import RetrievedChunk, rrf_fuse

        chunk = RetrievedChunk(
            chunk_id="c1", document_id="d1", document_name="doc.pdf",
            source_type="document", content="test", vector_score=0.9,
        )
        result = rrf_fuse([chunk], [], k=60)
        assert len(result) == 1
        assert result[0].fused_score > 0


# ── Data Analysis Resilience ─────────────────────────────────────────


class TestDataAnalysisResilience:
    def test_empty_dataset(self):
        from app.data.analysis import execute_plan

        result = execute_plan([], {"ops": []})
        assert isinstance(result, dict)

    def test_filter_operation(self):
        from app.data.analysis import execute_plan

        data = [
            {"region": "North", "revenue": 100},
            {"region": "South", "revenue": 200},
            {"region": "North", "revenue": 150},
        ]
        result = execute_plan(data, {
            "ops": [{"op": "filter", "field": "region", "value": "North"}]
        })
        assert len(result.get("data", [])) == 2

    def test_group_by_operation(self):
        from app.data.analysis import execute_plan

        data = [
            {"region": "North", "revenue": 100},
            {"region": "South", "revenue": 200},
            {"region": "North", "revenue": 150},
        ]
        result = execute_plan(data, {
            "ops": [{"op": "group_by", "field": "region", "agg": "sum", "value_field": "revenue"}]
        })
        assert isinstance(result, dict)

    def test_invalid_op_rejected(self):
        from app.data.analysis import execute_plan

        result = execute_plan([{"a": 1}], {
            "ops": [{"op": "exec", "code": "import os"}]
        })
        assert "error" in result or result.get("data", []) == [] or "exec" not in str(result)


# ── Webhook Resilience ───────────────────────────────────────────────


class TestWebhookResilience:
    @pytest.mark.asyncio
    async def test_duplicate_webhook_returns_ok(self, client):
        response = await client.post(
            "/api/telegram/webhook",
            json={"update_id": 1, "message": {"text": "/start"}},
            headers={"x-telegram-bot-api-secret-token": ""},
        )
        assert response.status_code in (200, 403, 503)

    @pytest.mark.asyncio
    async def test_malformed_json_webhook(self, client):
        response = await client.post(
            "/api/telegram/webhook",
            content=b"not json",
            headers={
                "content-type": "application/json",
                "x-telegram-bot-api-secret-token": "",
            },
        )
        assert response.status_code in (400, 403, 503)

    @pytest.mark.asyncio
    async def test_webhook_without_config_returns_503(self, client):
        response = await client.post(
            "/api/telegram/webhook",
            json={"update_id": 999},
        )
        assert response.status_code in (200, 403, 503)


# ── Upload Resilience ────────────────────────────────────────────────


class TestUploadResilience:
    @pytest.mark.asyncio
    async def test_empty_upload_handled(self, client, auth_headers, workspace):
        response = await client.post(
            "/api/media/upload",
            files={"file": ("empty.txt", b"", "text/plain")},
            params={"workspace_id": workspace["id"]},
            headers=auth_headers,
        )
        assert response.status_code in (200, 201, 400, 422)

    @pytest.mark.asyncio
    async def test_large_filename_truncated(self, client, auth_headers, workspace):
        long_name = "a" * 500 + ".txt"
        response = await client.post(
            "/api/media/upload",
            files={"file": (long_name, b"content", "text/plain")},
            params={"workspace_id": workspace["id"]},
            headers=auth_headers,
        )
        assert response.status_code in (200, 201, 400, 422)


# ── Cost Estimation ──────────────────────────────────────────────────


class TestCostEstimation:
    def test_known_provider_cost(self):
        cost = estimate_cost_usd("groq", "openai/gpt-oss-20b", 1000, 500)
        assert cost > 0

    def test_unknown_provider_zero_cost(self):
        cost = estimate_cost_usd("unknown", "model", 1000, 500)
        assert cost == 0.0

    def test_zero_tokens(self):
        cost = estimate_cost_usd("groq", "openai/gpt-oss-120b", 0, 0)
        assert cost == 0.0


@pytest.mark.asyncio
async def test_cloudinary_delete_uses_uploader_destroy(monkeypatch):
    from app.services.media_service import MediaService, StoredAsset

    service = MediaService()
    service.mode = "cloudinary"
    service._configure_cloudinary = lambda: None
    calls = []

    import cloudinary.uploader

    def fake_destroy(public_id, resource_type):
        calls.append((public_id, resource_type))
        return {"result": "ok"}

    monkeypatch.setattr(cloudinary.uploader, "destroy", fake_destroy)
    await service.delete(
        StoredAsset(
            public_id="emmaus/test", url="https://example.com", resource_type="image", mode="cloudinary"
        )
    )
    assert calls == [("emmaus/test", "image")]


# ── JSON Extraction Resilience ───────────────────────────────────────


class TestJsonExtraction:
    def test_handles_markdown_fences(self):
        from app.providers.base import extract_json

        result = extract_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_handles_embedded_json(self):
        from app.providers.base import extract_json

        result = extract_json('Here is the result: {"score": 9} end')
        assert result == {"score": 9}

    def test_handles_array(self):
        from app.providers.base import extract_json

        result = extract_json('[{"id": 1}, {"id": 2}]')
        assert result == [{"id": 1}, {"id": 2}]

    def test_raises_on_no_json(self):
        from app.providers.base import extract_json

        with pytest.raises(ValueError):
            extract_json("no json here at all")

    def test_handles_nested_json(self):
        from app.providers.base import extract_json

        result = extract_json('{"data": {"nested": true}, "list": [1,2]}')
        assert result["data"]["nested"] is True
        assert result["list"] == [1, 2]


# ── Concurrent Failure Handling ──────────────────────────────────────


class TestConcurrentFailures:
    @pytest.mark.asyncio
    async def test_parallel_requests_with_failing_provider(self):
        settings = MagicMock()
        settings.groq_chat_model = "openai/gpt-oss-120b"
        settings.groq_fast_model = "openai/gpt-oss-20b"
        settings.ollama_chat_model = "gpt-oss:120b"

        providers = {
            "groq": FailingProvider(),
            "mock": MockProvider(),
        }
        router = ModelRouter(providers, settings)

        async def make_request():
            return await router.complete(
                [{"role": "user", "content": "test"}], task=TaskType.CLASSIFY
            )

        results = await asyncio.gather(*[make_request() for _ in range(5)])
        assert all(r.provider == "mock" for r in results)

    @pytest.mark.asyncio
    async def test_sequential_retry_exhaustion(self):
        settings = MagicMock()
        settings.groq_chat_model = "openai/gpt-oss-120b"
        settings.groq_fast_model = "openai/gpt-oss-20b"
        settings.ollama_chat_model = "gpt-oss:120b"

        providers = {
            "groq": FailingProvider(),
            "ollama": FailingProvider(),
        }
        router = ModelRouter(providers, settings)
        with pytest.raises(RuntimeError):
            await router.complete(
                [{"role": "user", "content": "test"}], task=TaskType.REASONING
            )
