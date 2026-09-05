"""Tests for vision on-demand analysis and dataset readiness wait."""

import asyncio

import pytest

import app.agents.graph as graph
import app.core.db as db_module
import app.vision.analyzer as analyzer_module


FAKE_ANALYSIS = {
    "description": "A test chart",
    "extracted_text": "Q3 revenue",
    "is_handwritten": False,
    "key_observations": ["bar chart"],
    "confidence": 0.9,
}


@pytest.mark.asyncio
async def test_vision_on_demand_when_analysis_missing(tmp_path, monkeypatch):
    ws_id, media_id = "ws-vis-1", "med-vis-1"
    monkeypatch.setattr(graph, "_LOCAL_MEDIA_DIR", tmp_path)
    (tmp_path / ws_id).mkdir(parents=True)
    (tmp_path / ws_id / "pic.jpg").write_bytes(b"\xff\xd8\xff\x00fakejpeg")

    async def fake_analyze(data: bytes, mime: str):
        assert data.startswith(b"\xff\xd8\xff")
        return dict(FAKE_ANALYSIS)

    monkeypatch.setattr(analyzer_module, "analyze_image", fake_analyze)
    await db_module._db.media_assets.insert_one(
        {
            "_id": media_id,
            "workspace_id": ws_id,
            "kind": "image",
            "filename": "pic.jpg",
            "url": f"/media/{ws_id}/pic.jpg",
            "public_id": f"{ws_id}/pic.jpg",
            "storage_mode": "local",
        }
    )
    out = await graph.vision_node(
        {"workspace_id": ws_id, "attachment_ids": [media_id]}
    )
    assert len(out["vision_results"]) == 1
    assert out["vision_results"][0]["description"] == "A test chart"
    stored = await db_module._db.media_assets.find_one({"_id": media_id})
    assert stored["analysis"]["description"] == "A test chart"


@pytest.mark.asyncio
async def test_vision_skips_on_demand_when_analysis_present(monkeypatch):
    ws_id, media_id = "ws-vis-2", "med-vis-2"
    calls: list = []

    async def fake_analyze(data: bytes, mime: str):
        calls.append(1)
        return dict(FAKE_ANALYSIS)

    monkeypatch.setattr(analyzer_module, "analyze_image", fake_analyze)
    await db_module._db.media_assets.insert_one(
        {
            "_id": media_id,
            "workspace_id": ws_id,
            "kind": "image",
            "filename": "pic.jpg",
            "url": "/media/x/pic.jpg",
            "public_id": "x/pic.jpg",
            "storage_mode": "local",
            "analysis": dict(FAKE_ANALYSIS),
        }
    )
    out = await graph.vision_node(
        {"workspace_id": ws_id, "attachment_ids": [media_id]}
    )
    assert len(out["vision_results"]) == 1
    assert calls == []


@pytest.mark.asyncio
async def test_data_node_waits_for_processing_dataset(monkeypatch):
    ws_id, ds_id = "ws-data-1", "ds-data-1"

    async def fake_analyze(dataset: dict, question: str, ctx=None):
        return {
            "dataset_name": dataset["filename"],
            "summary": "ok",
            "chart": None,
            "error": None,
        }

    monkeypatch.setattr(graph, "analyze_dataset", fake_analyze)
    await db_module._db.datasets.insert_one(
        {
            "_id": ds_id,
            "workspace_id": ws_id,
            "filename": "sales.csv",
            "status": "processing",
            "num_rows": 10,
        }
    )

    async def flip_ready():
        await asyncio.sleep(1)
        await db_module._db.datasets.update_one(
            {"_id": ds_id}, {"$set": {"status": "ready"}}
        )

    flip_task = asyncio.create_task(flip_ready())
    out = await graph.data_node({"workspace_id": ws_id, "question": "total?"})
    await flip_task
    assert len(out["data_results"]) == 1
    assert out["data_results"][0]["error"] is None
