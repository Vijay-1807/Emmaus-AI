"""Unit tests for answer generation (citation fallback behavior)."""

import pytest

from app.agents.graph import GENERATE_SYSTEM, generate_node


def _evidence():
    return [
        {
            "kind": "document",
            "source_name": "report.pdf",
            "summary": "Revenue was $2.4M in Q3.",
            "citation": {
                "chunk_id": "c1",
                "document_id": "d1",
                "document_name": "report.pdf",
                "source_type": "document",
                "page": 1,
                "section": None,
                "snippet": "Revenue was $2.4M in Q3.",
                "score": 0.9,
                "media_url": None,
            },
            "chart": None,
        },
        {
            "kind": "document",
            "source_name": "notes.txt",
            "summary": "Q3 notes.",
            "citation": {
                "chunk_id": "c2",
                "document_id": "d1",
                "document_name": "notes.txt",
                "source_type": "document",
                "page": None,
                "section": None,
                "snippet": "Q3 notes.",
                "score": 0.5,
                "media_url": None,
            },
            "chart": None,
        },
    ]


@pytest.mark.asyncio
async def test_generate_falls_back_to_evidence_citations():
    """Mock answers carry no [N] markers; Sources must still list retrieved docs."""
    state = {
        "question": "What was revenue?",
        "evidence": _evidence(),
        "history": [],
        "verification": {"confidence": 0.9},
    }
    out = await generate_node(state)
    assert out["answer"], "expected a generated answer"
    assert out["citations"], "expected fallback citations from evidence"
    assert {c["document_name"] for c in out["citations"]} <= {"report.pdf", "notes.txt"}


@pytest.mark.asyncio
async def test_generate_no_evidence_no_citations():
    state = {
        "question": "What was revenue?",
        "evidence": [],
        "history": [],
        "verification": {"confidence": 0.2},
    }
    out = await generate_node(state)
    assert out["answer"]
    assert out["citations"] == []


def test_generate_system_bans_code_dumps_with_charts():
    # Answers with attached charts must describe, never paste codeblobs.
    assert "Never paste code blocks or data-URI image markdown" in GENERATE_SYSTEM


def _chart_evidence():
    ev = _evidence()
    ev = [dict(ev[0], chart={
        "chart_type": "bar",
        "title": "T",
        "labels": ["A"],
        "series": [{"name": "v", "values": [1]}],
    }), ev[1]]
    return ev


class _StreamRouter:
    def __init__(self, pieces):
        self._pieces = pieces
        self.emitted = []

    async def stream(self, *args, **kwargs):
        for piece in self._pieces:
            self.emitted.append(piece)
            yield piece


@pytest.mark.asyncio
async def test_generate_strips_code_fences_when_charts_present(monkeypatch):
    import app.agents.graph as graph

    pieces = [
        "Here is the chart:\n",
        "```python\nimport pandas as pd\nprint(df)\n```\n",
        "Done.\n",
    ]
    monkeypatch.setattr(graph, "get_model_router", lambda: _StreamRouter(pieces))
    state = {
        "question": "make a bar chart of Percentage by Metric",
        "evidence": _chart_evidence(),
        "history": [],
        "verification": {"confidence": 0.9},
    }
    out = await generate_node(state)
    assert "```" not in out["answer"]
    assert "import pandas" not in out["answer"]
    assert "Here is the chart:" in out["answer"]
    assert "Done." in out["answer"]


@pytest.mark.asyncio
async def test_generate_keeps_code_when_user_asks(monkeypatch):
    import app.agents.graph as graph

    pieces = ["Here you go:\n", "```python\nprint(1)\n```\n"]
    monkeypatch.setattr(graph, "get_model_router", lambda: _StreamRouter(pieces))
    state = {
        "question": "give me python code to plot this",
        "evidence": _chart_evidence(),
        "history": [],
        "verification": {"confidence": 0.9},
    }
    out = await generate_node(state)
    assert "```python" in out["answer"]
