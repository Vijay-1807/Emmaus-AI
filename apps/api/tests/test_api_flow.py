import asyncio
import json
from datetime import datetime, timezone

import pytest

import app.core.db as db_module


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "mock" in body["providers"]["providers"]


@pytest.mark.asyncio
async def test_auth_flow(client):
    register = await client.post(
        "/api/auth/register",
        json={"email": "flow@emmaus.ai", "password": "supersecret123", "name": "Flow"},
    )
    assert register.status_code == 201
    tokens = register.json()
    assert tokens["access_token"] and tokens["refresh_token"]

    duplicate = await client.post(
        "/api/auth/register",
        json={"email": "flow@emmaus.ai", "password": "supersecret123", "name": "Flow"},
    )
    assert duplicate.status_code == 409

    bad_login = await client.post(
        "/api/auth/login", json={"email": "flow@emmaus.ai", "password": "wrong"}
    )
    assert bad_login.status_code == 401

    refreshed = await client.post(
        "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200

    me = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "flow@emmaus.ai"

    me_no_token = await client.get("/api/auth/me")
    assert me_no_token.status_code == 401


@pytest.mark.asyncio
async def test_anonymous_auth_flow(client):
    response = await client.post("/api/auth/anonymous")
    assert response.status_code == 201, response.text
    tokens = response.json()
    assert tokens["access_token"] and tokens["refresh_token"]
    assert tokens["user"]["email"].endswith("@guest.emmaus.ai")

    me = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["name"] == "Guest"


@pytest.mark.asyncio
async def test_workspace_isolation(client, auth_headers, workspace):
    other = await client.post(
        "/api/auth/register",
        json={"email": "other@emmaus.ai", "password": "supersecret123", "name": "Other"},
    )
    other_token = other.json()["access_token"]
    response = await client.get(
        f"/api/workspaces/{workspace['id']}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_document_upload_and_processing(client, auth_headers, workspace):
    content = (
        "# Q3 Report\n"
        "Total revenue for Q3 was $2.4M, down from $3.1M in Q2. "
        "The decline was driven primarily by the South region, which contributed "
        "63 percent of the total drop due to supply chain delays.\n\n"
        "## Marketing\nMarketing spend was $300K in Q3, about 12.5 percent of revenue."
    ).encode()
    response = await client.post(
        "/api/documents/upload",
        params={"workspace_id": workspace["id"]},
        files={"file": ("quarterly_report.txt", content, "text/plain")},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["status"] in ("processing", "ready")

    for _ in range(100):
        detail = await client.get(
            f"/api/documents/{document['id']}",
            params={"workspace_id": workspace["id"]},
            headers=auth_headers,
        )
        if detail.json()["status"] != "processing":
            break
        await asyncio.sleep(0.05)
    assert detail.json()["status"] == "ready", detail.json()
    assert detail.json()["num_chunks"] >= 1


@pytest.mark.asyncio
async def test_document_upload_rejects_bad_type(client, auth_headers, workspace):
    response = await client.post(
        "/api/documents/upload",
        params={"workspace_id": workspace["id"]},
        files={"file": ("evil.exe", b"MZ...", "application/octet-stream")},
        headers=auth_headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_dataset_upload_and_profile(client, auth_headers, workspace):
    csv_bytes = b"region,quarter,revenue\nnorth,Q2,100\nsouth,Q2,80\nnorth,Q3,110\nsouth,Q3,40\n"
    response = await client.post(
        "/api/datasets/upload",
        params={"workspace_id": workspace["id"]},
        files={"file": ("sales.csv", csv_bytes, "text/csv")},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    dataset_id = response.json()["id"]

    for _ in range(100):
        detail = await client.get(
            f"/api/datasets/{dataset_id}",
            params={"workspace_id": workspace["id"]},
            headers=auth_headers,
        )
        if detail.json()["status"] != "processing":
            break
        await asyncio.sleep(0.05)
    dataset = detail.json()
    assert dataset["status"] == "ready", dataset
    assert dataset["num_rows"] == 4
    assert dataset["num_columns"] == 3
    assert any(c["name"] == "region" for c in dataset["columns"])


@pytest.mark.asyncio
async def test_chat_stream_end_to_end(client, auth_headers, workspace):
    content = (
        "# Q3 Report\n"
        "Total revenue for Q3 was $2.4M, down from $3.1M in Q2. "
        "The decline was driven primarily by the South region."
    ).encode()
    upload = await client.post(
        "/api/documents/upload",
        params={"workspace_id": workspace["id"]},
        files={"file": ("report.txt", content, "text/plain")},
        headers=auth_headers,
    )
    document_id = upload.json()["id"]
    for _ in range(100):
        detail = await client.get(
            f"/api/documents/{document_id}",
            params={"workspace_id": workspace["id"]},
            headers=auth_headers,
        )
        if detail.json()["status"] != "processing":
            break
        await asyncio.sleep(0.05)

    events = []
    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={
            "workspace_id": workspace["id"],
            "message": "Why did revenue decline in Q3?",
        },
        headers=auth_headers,
    ) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line.removeprefix("data: ").strip()
            if payload == "[STREAM_END]":
                break
            events.append(json.loads(payload))

    types = [e["type"] for e in events]
    assert "node" in types
    assert "token" in types
    assert "done" in types
    done_event = next(e for e in events if e["type"] == "done")
    assert done_event["investigation"]["answer"]
    assert done_event["investigation"]["conversation_id"]
    assert done_event["investigation"]["model_runs"]

    conversations = await client.get(
        "/api/chat/conversations", params={"workspace_id": workspace["id"]}, headers=auth_headers
    )
    assert conversations.status_code == 200
    assert len(conversations.json()) >= 1

    investigations = await client.get(
        "/api/investigations", params={"workspace_id": workspace["id"]}, headers=auth_headers
    )
    assert investigations.status_code == 200
    assert len(investigations.json()) >= 1


@pytest.mark.asyncio
async def test_investigation_delete(client, auth_headers, workspace):
    doc = {
        "_id": "inv-delete-1",
        "workspace_id": workspace["id"],
        "question": "delete me",
        "answer": "bye",
        "created_at": datetime.now(timezone.utc),
    }
    await db_module._db["investigations"].insert_one(dict(doc))

    listing = await client.get(
        "/api/investigations", params={"workspace_id": workspace["id"]}, headers=auth_headers
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    deleted = await client.delete(
        f"/api/investigations/{doc['_id']}",
        params={"workspace_id": workspace["id"]},
        headers=auth_headers,
    )
    assert deleted.status_code == 204

    listing = await client.get(
        "/api/investigations", params={"workspace_id": workspace["id"]}, headers=auth_headers
    )
    assert listing.json() == []

    again = await client.delete(
        f"/api/investigations/{doc['_id']}",
        params={"workspace_id": workspace["id"]},
        headers=auth_headers,
    )
    assert again.status_code == 404

    other = await client.post(
        "/api/workspaces", json={"name": "Other"}, headers=auth_headers
    )
    other_id = other.json()["id"]
    await db_module._db["investigations"].insert_one({**doc, "_id": "inv-delete-2"})
    cross = await client.delete(
        "/api/investigations/inv-delete-2",
        params={"workspace_id": other_id},
        headers=auth_headers,
    )
    assert cross.status_code == 404


@pytest.mark.asyncio
async def test_observability_after_chat(client, auth_headers, workspace):
    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"workspace_id": workspace["id"], "message": "Hello there"},
        headers=auth_headers,
    ) as response:
        async for line in response.aiter_lines():
            if line.strip() == "data: [STREAM_END]":
                break

    summary = await client.get(
        "/api/observability/summary", params={"workspace_id": workspace["id"]}, headers=auth_headers
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["total_investigations"] >= 1

    traces = await client.get(
        "/api/observability/traces", params={"workspace_id": workspace["id"]}, headers=auth_headers
    )
    assert traces.status_code == 200
    assert len(traces.json()) >= 1


@pytest.mark.asyncio
async def test_evaluation_seeding_and_listing(client, auth_headers, workspace):
    case = await client.post(
        "/api/evaluation/cases",
        json={
            "question": "What was Q3 revenue?",
            "expected_answer": "$2.4M",
            "expected_document_names": ["report.txt"],
            "category": "direct",
        },
        headers=auth_headers,
    )
    assert case.status_code == 201
    cases = await client.get("/api/evaluation/cases", headers=auth_headers)
    assert cases.status_code == 200
    assert len(cases.json()) == 1


@pytest.mark.asyncio
async def test_evaluation_run_end_to_end(client, auth_headers, workspace):
    seed = await client.post(
        "/api/evaluation/cases",
        json={
            "question": "What was Q3 revenue?",
            "expected_answer": "$2.4M",
            "expected_document_names": ["report.txt"],
            "category": "direct",
        },
        headers=auth_headers,
    )
    assert seed.status_code == 201

    run = await client.post(
        "/api/evaluation/run",
        json={"workspace_id": workspace["id"], "retrieval_mode": "hybrid_rerank", "max_cases": 5},
        headers=auth_headers,
    )
    assert run.status_code == 201, run.text
    assert run.json()["status"] == "running"

    final = None
    for _ in range(100):
        await asyncio.sleep(0.2)
        runs = await client.get(
            "/api/evaluation/runs", params={"workspace_id": workspace["id"]}, headers=auth_headers
        )
        assert runs.status_code == 200
        if runs.json() and runs.json()[0]["status"] != "running":
            final = runs.json()[0]
            break
    assert final is not None, "evaluation run never finished"
    assert final["status"] == "completed"
    assert final["num_cases"] >= 1


@pytest.mark.asyncio
async def test_evaluation_run_without_cases_fails_clearly(client, auth_headers, workspace):
    run = await client.post(
        "/api/evaluation/run",
        json={"workspace_id": workspace["id"], "retrieval_mode": "hybrid_rerank", "max_cases": 5},
        headers=auth_headers,
    )
    assert run.status_code == 201, run.text

    final = None
    for _ in range(50):
        await asyncio.sleep(0.2)
        runs = await client.get(
            "/api/evaluation/runs", params={"workspace_id": workspace["id"]}, headers=auth_headers
        )
        assert runs.status_code == 200
        if runs.json() and runs.json()[0]["status"] != "running":
            final = runs.json()[0]
            break
    assert final is not None, "evaluation run never finished"
    assert final["status"] == "failed"
    assert final["error"] == "no evaluation cases found"


@pytest.mark.asyncio
async def test_seed_from_history(client, auth_headers, workspace):
    from datetime import datetime, timezone

    empty = await client.post(
        "/api/evaluation/seed-from-history",
        json={"workspace_id": workspace["id"]},
        headers=auth_headers,
    )
    assert empty.status_code == 400

    await db_module._db["investigations"].insert_one(
        {
            "_id": "inv-seed-1",
            "workspace_id": workspace["id"],
            "question": "What was Q3 revenue?",
            "answer": "Revenue was $2.4M.",
            "citations": [{"document_name": "report.txt"}],
            "created_at": datetime.now(timezone.utc),
        }
    )
    seeded = await client.post(
        "/api/evaluation/seed-from-history",
        json={"workspace_id": workspace["id"]},
        headers=auth_headers,
    )
    assert seeded.status_code == 200
    assert seeded.json()["inserted"] == 1

    # Idempotent — same investigation won't seed twice.
    again = await client.post(
        "/api/evaluation/seed-from-history",
        json={"workspace_id": workspace["id"]},
        headers=auth_headers,
    )
    assert again.status_code == 400


@pytest.mark.asyncio
async def test_health_reports_storage_and_telegram(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["storage"]["mode"] in ("cloudinary", "local")
    assert isinstance(body["storage"]["cloudinary_configured"], bool)
    assert isinstance(body["telegram"]["configured"], bool)


@pytest.mark.asyncio
async def test_clear_workspace_and_storage_summary(client, auth_headers, workspace):
    # Check storage summary
    summary = await client.get(
        f"/api/workspaces/{workspace['id']}/storage-summary", headers=auth_headers
    )
    assert summary.status_code == 200
    data = summary.json()
    assert "documents" in data
    assert "datasets" in data
    assert "total_size_bytes" in data

    # Clear workspace
    clear_res = await client.post(
        f"/api/workspaces/{workspace['id']}/clear", headers=auth_headers
    )
    assert clear_res.status_code == 200
    body = clear_res.json()
    assert "details" in body
    assert body["details"]["workspace_id"] == workspace["id"]

    # Verify summary is now zeroed
    summary2 = await client.get(
        f"/api/workspaces/{workspace['id']}/storage-summary", headers=auth_headers
    )
    assert summary2.status_code == 200
    data2 = summary2.json()
    assert data2["documents"]["count"] == 0
    assert data2["datasets"]["count"] == 0
