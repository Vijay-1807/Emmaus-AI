import os

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "SECRET_KEY": "test-secret-key-for-ci-with-32-bytes-minimum",
        "MONGODB_URI": "mongodb://test.invalid",
        "MONGODB_DB": "vedax-test",
        "EMBEDDING_PROVIDER": "mock",
        "MEDIA_STORAGE": "local",
        "CEREBRAS_API_KEY": "",
        "GROQ_API_KEY": "",
        "OLLAMA_API_KEY": "",
        "GEMINI_API_KEY": "",
        "SARVAM_API_KEY": "",
        "DEEPGRAM_API_KEY": "",
        "CLOUDINARY_CLOUD_NAME": "",
        "CLOUDINARY_API_KEY": "",
        "CLOUDINARY_API_SECRET": "",
        "LANGFUSE_PUBLIC_KEY": "",
        "LANGFUSE_SECRET_KEY": "",
        "TELEGRAM_BOT_TOKEN": "",
    }
)

import httpx
import pytest

import app.core.db as db_module
from mongomock_motor import AsyncMongoMockClient

_mock_client = AsyncMongoMockClient()
db_module._client = _mock_client
db_module._db = _mock_client["vedax-test"]

COLLECTIONS = [
    "users",
    "refresh_tokens",
    "workspaces",
    "documents",
    "document_chunks",
    "datasets",
    "media_assets",
    "conversations",
    "messages",
    "investigations",
    "model_runs",
    "tool_runs",
    "evaluation_cases",
    "evaluation_runs",
    "telegram_links",
    "telegram_updates",
]


@pytest.fixture(autouse=True)
async def clean_db():
    for name in COLLECTIONS:
        await db_module._db[name].delete_many({})
    yield


@pytest.fixture
async def client():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
async def auth_headers(client):
    response = await client.post(
        "/api/auth/register",
        json={"email": "tester@emmaus.ai", "password": "supersecret123", "name": "Tester"},
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def workspace(client, auth_headers):
    response = await client.post(
        "/api/workspaces", json={"name": "Test Workspace", "description": "tests"}, headers=auth_headers
    )
    assert response.status_code == 201, response.text
    return response.json()
