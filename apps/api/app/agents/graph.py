import logging
import re
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents import events
from app.agents.state import InvestigationState
from app.core.db import get_db
from app.data.analysis import analyze_dataset
from app.providers.base import TaskType
from app.providers.registry import get_model_router
from app.rag.query import rewrite_query
from app.rag.retriever import get_retriever

logger = logging.getLogger("vedax.graph")

CLASSIFY_PROMPT = """You route requests for a multimodal analysis system.

Available sources in the workspace:
{sources}

Conversation history (latest last):
{history}

User question: {question}

Choose which capabilities are needed:
- "rag": needs facts, explanations or evidence from documents/notes/transcripts
- "data": needs calculation over structured datasets (CSV/XLSX numbers, trends, comparisons)
- "vision": needs understanding of attached images, charts, screenshots or handwriting
- []: general conversation or questions answerable without workspace sources

Respond ONLY with JSON:
{{"capabilities": [...], "intent": "question|analysis|chat|summary", "reasoning": "<short>"}}"""

VERIFY_PROMPT = """You verify evidence quality for an investigation.

Question: {question}

Evidence collected:
{evidence}

Respond ONLY with JSON:
{{"sufficient": <true|false>, "confidence": <0.0-1.0>, "reasoning": "<one sentence>", "missing": "<what is missing, or empty>"}}"""

GENERATE_SYSTEM = """You are VedaX AI, a rigorous multimodal analyst.

Rules:
- Ground every factual claim in the numbered evidence below and cite as [1], [2]...
- Combine document evidence, dataset analysis results, image observations and transcripts when available.
- Include key numbers exactly as they appear in the evidence.
- If evidence is insufficient for part of the question, say so explicitly instead of guessing.
- Be direct and structured. Use short paragraphs or bullets.
- End with a line: "Confidence: <low|medium|high> — <one short reason>"."""


async def _workspace_inventory(workspace_id: str) -> tuple[list[dict], list[dict]]:
    db = get_db()
    documents = [
        {"id": d["_id"], "name": d["filename"], "type": d["source_type"]}
        async for d in db.documents.find(
            {"workspace_id": workspace_id, "status": "ready"}, {"filename": 1, "source_type": 1}
        ).limit(50)
    ]
    datasets = [
        {"id": d["_id"], "name": d["filename"], "rows": d.get("num_rows", 0)}
        async for d in db.datasets.find(
            {"workspace_id": workspace_id, "status": "ready"}, {"filename": 1, "num_rows": 1}
        ).limit(20)
    ]
    return documents, datasets


async def transcribe_node(state: InvestigationState) -> dict:
    db = get_db()
    question = state["question"]
    audio_transcript = None
    audio_id = state.get("audio_media_id")
    if audio_id:
        media = await db.media_assets.find_one({"_id": audio_id})
        if media and media.get("transcript"):
            audio_transcript = media["transcript"]
            if not question.strip():
                question = audio_transcript
    events.emit({"type": "node", "node": "transcribe", "detail": "voice input ready"})
    return {"question": question, "audio_transcript": audio_transcript}


async def classify_node(state: InvestigationState) -> dict:
    db = get_db()
    documents, datasets = await _workspace_inventory(state["workspace_id"])
    sources = []
    for d in documents:
        sources.append(f"- document: {d['name']} ({d['type']})")
    for d in datasets:
        sources.append(f"- dataset: {d['name']} ({d['rows']} rows)")
    if not sources:
        sources.append("- (none)")
    history_text = "\n".join(
        f"{'User' if m.get('role') == 'user' else 'Assistant'}: {str(m.get('content', ''))[:200]}"
        for m in (state.get("history") or [])[-6:]
    ) or "(empty)"
    prompt = CLASSIFY_PROMPT.format(
        sources="\n".join(sources), history=history_text, question=state["question"]
    )
    ctx = events.get_run_ctx()
    capabilities: list[str] = []
    intent = "question"
    try:
        router = get_model_router()
        data, _ = await router.complete_json(
            [{"role": "user", "content": prompt}], task=TaskType.CLASSIFY, ctx=ctx
        )
        raw = data.get("capabilities", [])
        if isinstance(raw, list):
            capabilities = [c for c in raw if c in ("rag", "data", "vision")]
        intent = str(data.get("intent", "question"))
    except Exception as exc:
        logger.warning("classification failed, defaulting to rag: %s", exc)
        capabilities = ["rag"] if documents else []
    if datasets and "data" not in capabilities and any(
        w in state["question"].lower() for w in ("how much", "how many", "trend", "revenue", "compare", "percentage", "average", "total", "growth", "decline", "increase", "decrease")
    ):
        capabilities.append("data")
    if not capabilities and (documents or datasets):
        capabilities = ["rag"]
    events.emit(
        {
            "type": "node",
            "node": "classify",
            "detail": f"route: {', '.join(capabilities) or 'direct answer'}",
            "capabilities": capabilities,
        }
    )
    return {
        "capabilities": capabilities,
        "intent": intent,
        "workspace_sources": documents + datasets,
    }


def _route_capabilities(state: InvestigationState) -> list[str]:
    capabilities = state.get("capabilities") or []
    targets = [c for c in capabilities if c in ("rag", "data", "vision")]
    return targets or ["fuse"]


async def rag_node(state: InvestigationState) -> dict:
    ctx = events.get_run_ctx()
    question = state["question"]
    rewritten = question
    if state.get("history") or state.get("retry_count", 0) > 0:
        rewritten = await rewrite_query(
            question, state.get("history") or [], ctx=ctx
        )
    attachment_docs = await _resolve_attachment_documents(state)
    retriever = get_retriever()
    mode = state.get("retrieval_mode") or "hybrid_rerank"
    chunks = await retriever.retrieve(
        state["workspace_id"],
        rewritten,
        mode=mode,
        document_ids=attachment_docs or None,
    )
    serialized = [
        {
            "chunk_id": c.chunk_id,
            "document_id": c.document_id,
            "document_name": c.document_name,
            "source_type": c.source_type,
            "content": c.content,
            "page": c.page,
            "section": c.section,
            "score": c.best_score,
        }
        for c in chunks
    ]
    events.emit(
        {
            "type": "node",
            "node": "rag",
            "detail": f"{len(serialized)} passages retrieved (mode: {mode})",
            "query": rewritten,
            "count": len(serialized),
        }
    )
    return {"retrieved_chunks": serialized, "rewritten_query": rewritten}


async def _resolve_attachment_documents(state: InvestigationState) -> list[str]:
    db = get_db()
    attachment_ids = state.get("attachment_ids") or []
    if not attachment_ids:
        return []
    found = []
    for attachment_id in attachment_ids:
        document = await db.documents.find_one(
            {"_id": attachment_id, "workspace_id": state["workspace_id"]}, {"_id": 1}
        )
        if document:
            found.append(attachment_id)
    return found


async def data_node(state: InvestigationState) -> dict:
    db = get_db()
    ctx = events.get_run_ctx()
    attachment_ids = state.get("attachment_ids") or []
    cursor = db.datasets.find({"workspace_id": state["workspace_id"], "status": "ready"})
    targets = []
    async for dataset in cursor:
        if not attachment_ids or dataset["_id"] in attachment_ids:
            targets.append(dataset)
    targets = targets[:3]
    if not targets:
        events.emit({"type": "node", "node": "data", "detail": "no datasets available"})
        return {"data_results": []}
    events.emit(
        {"type": "node", "node": "data", "detail": f"analyzing {len(targets)} dataset(s)"}
    )
    results = []
    for dataset in targets:
        result = await analyze_dataset(dataset, state["question"], ctx=ctx)
        results.append(result)
        ctx.report(
            {
                "tool": "pandas_analyze",
                "input": {"dataset": dataset.get("filename"), "question": state["question"]},
                "success": result.get("error") is None,
                "latency_ms": 0,
            }
        )
    events.emit(
        {
            "type": "node",
            "node": "data",
            "detail": "dataset analysis complete",
            "charts": [r["chart"] for r in results if r.get("chart")],
        }
    )
    return {"data_results": results}


async def vision_node(state: InvestigationState) -> dict:
    db = get_db()
    attachment_ids = state.get("attachment_ids") or []
    results = []
    if attachment_ids:
        for attachment_id in attachment_ids:
            media = await db.media_assets.find_one(
                {"_id": attachment_id, "kind": "image"}
            )
            if media and media.get("analysis"):
                results.append(
                    {
                        "source_name": media.get("filename", "image"),
                        "description": media["analysis"].get("description", ""),
                        "extracted_text": media["analysis"].get("extracted_text", ""),
                        "is_handwritten": media["analysis"].get("is_handwritten", False),
                        "key_observations": media["analysis"].get("key_observations", []),
                        "confidence": media["analysis"].get("confidence", 0.0),
                        "media_url": media.get("url"),
                    }
                )
                continue
            document = await db.documents.find_one(
                {"_id": attachment_id, "source_type": "image"}
            )
            if document and document.get("analysis"):
                results.append(
                    {
                        "source_name": document["filename"],
                        "description": document["analysis"].get("description", ""),
                        "extracted_text": document["analysis"].get("extracted_text", ""),
                        "is_handwritten": document["analysis"].get("is_handwritten", False),
                        "key_observations": document["analysis"].get("key_observations", []),
                        "confidence": document["analysis"].get("confidence", 0.0),
                        "media_url": (document.get("media") or {}).get("url"),
                    }
                )
    events.emit(
        {"type": "node", "node": "vision", "detail": f"{len(results)} image(s) analyzed"}
    )
    return {"vision_results": results}


async def fuse_node(state: InvestigationState) -> dict:
    db = get_db()
    evidence: list[dict] = []
    chunks = state.get("retrieved_chunks") or []
    doc_media: dict[str, str | None] = {}
    for chunk in chunks:
        doc_id = chunk.get("document_id")
        if doc_id and doc_id not in doc_media:
            document = await db.documents.find_one({"_id": doc_id}, {"media": 1})
            doc_media[doc_id] = (document.get("media") or {}).get("url") if document else None
    for chunk in chunks:
        evidence.append(
            {
                "kind": "document",
                "source_name": chunk.get("document_name", "document"),
                "summary": chunk.get("content", ""),
                "citation": {
                    "chunk_id": chunk.get("chunk_id"),
                    "document_id": chunk.get("document_id"),
                    "document_name": chunk.get("document_name"),
                    "source_type": chunk.get("source_type"),
                    "page": chunk.get("page"),
                    "section": chunk.get("section"),
                    "snippet": (chunk.get("content", ""))[:300],
                    "score": chunk.get("score", 0.0),
                    "media_url": doc_media.get(chunk.get("document_id")),
                },
                "chart": None,
            }
        )
    for result in state.get("data_results") or []:
        evidence.append(
            {
                "kind": "data",
                "source_name": result.get("dataset_name", "dataset"),
                "summary": result.get("summary", ""),
                "citation": None,
                "chart": result.get("chart"),
            }
        )
    for result in state.get("vision_results") or []:
        observations = "\n".join(f"- {o}" for o in result.get("key_observations", []))
        summary = result.get("description", "")
        if result.get("extracted_text"):
            summary += f"\nExtracted text:\n{result['extracted_text']}"
        if observations:
            summary += f"\nKey observations:\n{observations}"
        evidence.append(
            {
                "kind": "vision",
                "source_name": result.get("source_name", "image"),
                "summary": summary,
                "citation": None,
                "chart": None,
                "media_url": result.get("media_url"),
            }
        )
    transcript = state.get("audio_transcript")
    if transcript and state.get("question") != transcript:
        evidence.append(
            {
                "kind": "audio",
                "source_name": "voice input",
                "summary": f"Transcript: {transcript}",
                "citation": None,
                "chart": None,
            }
        )
    events.emit({"type": "evidence", "evidence": evidence[:12]})
    return {"evidence": evidence}


async def verify_node(state: InvestigationState) -> dict:
    ctx = events.get_run_ctx()
    capabilities = state.get("capabilities") or []
    evidence = state.get("evidence") or []
    if not capabilities or not any(c in capabilities for c in ("rag", "data", "vision")):
        verification = {"sufficient": True, "confidence": 0.75, "reasoning": "direct answer"}
        events.emit({"type": "node", "node": "verify", "detail": "direct answer mode"})
        return {"verification": verification}
    if not evidence:
        verification = {
            "sufficient": False,
            "confidence": 0.2,
            "reasoning": "no evidence retrieved",
        }
        retry = state.get("retry_count", 0)
        if retry == 0 and "rag" in capabilities:
            events.emit(
                {"type": "node", "node": "verify", "detail": "no evidence, retrying retrieval"}
            )
            return {"verification": verification, "retry_count": retry + 1}
        events.emit({"type": "node", "node": "verify", "detail": "no evidence available"})
        return {"verification": verification, "retry_count": retry + 1}
    evidence_text = "\n".join(
        f"[{i + 1}] ({e['kind']}/{e['source_name']}) {e['summary'][:280]}"
        for i, e in enumerate(evidence[:10])
    )
    prompt = VERIFY_PROMPT.format(question=state["question"], evidence=evidence_text)
    verification = {"sufficient": True, "confidence": 0.8, "reasoning": ""}
    try:
        router = get_model_router()
        data, _ = await router.complete_json(
            [{"role": "user", "content": prompt}], task=TaskType.VERIFY, ctx=ctx
        )
        verification = {
            "sufficient": bool(data.get("sufficient", True)),
            "confidence": float(data.get("confidence", 0.7)),
            "reasoning": str(data.get("reasoning", ""))[:300],
            "missing": str(data.get("missing", ""))[:300],
        }
    except Exception as exc:
        logger.warning("verification failed: %s", exc)
    retry = state.get("retry_count", 0)
    if not verification["sufficient"] and retry == 0 and "rag" in capabilities:
        events.emit(
            {
                "type": "node",
                "node": "verify",
                "detail": f"evidence insufficient: {verification['reasoning'][:80]} — retrying",
            }
        )
        return {"verification": verification, "retry_count": retry + 1}
    events.emit(
        {
            "type": "node",
            "node": "verify",
            "detail": f"confidence {verification['confidence']:.0%}",
        }
    )
    return {"verification": verification}


def _route_verify(state: InvestigationState) -> str:
    verification = state.get("verification") or {}
    retry = state.get("retry_count", 0)
    if not verification.get("sufficient", True) and retry == 1 and "rag" in (
        state.get("capabilities") or []
    ):
        return "rag"
    return "generate"


async def generate_node(state: InvestigationState) -> dict:
    ctx = events.get_run_ctx()
    evidence = state.get("evidence") or []
    blocks = []
    citation_map: dict[int, dict] = {}
    for index, piece in enumerate(evidence, start=1):
        blocks.append(f"[{index}] Source: {piece['source_name']} ({piece['kind']})")
        blocks.append(piece["summary"][:1500])
        blocks.append("")
        citation = piece.get("citation")
        if citation:
            citation_map[index] = citation
    if not blocks:
        blocks.append("(no evidence collected)")
    context = "\n".join(blocks)
    history = state.get("history") or []
    history_lines = [
        {"role": m.get("role", "user"), "content": str(m.get("content", ""))[:1500]}
        for m in history[-6:]
    ]
    messages = [{"role": "system", "content": GENERATE_SYSTEM}]
    messages.extend(history_lines)
    messages.append(
        {
            "role": "user",
            "content": f"Question: {state['question']}\n\nEvidence:\n{context}",
        }
    )
    events.emit({"type": "node", "node": "generate", "detail": "composing answer"})
    router = get_model_router()
    answer = ""
    try:
        stream = await router.stream(
            messages, task=TaskType.REASONING, temperature=0.2, max_tokens=3000, ctx=ctx
        )
        async for piece in stream:
            answer += piece
            events.emit({"type": "token", "text": piece})
    except Exception as exc:
        logger.error("generation failed: %s", exc)
        answer = (
            "I could not generate a final answer due to a model provider error. "
            f"Please try again. (Error: {str(exc)[:150]})"
        )
        events.emit({"type": "token", "text": answer})
    used = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)})
    citations = [citation_map[n] for n in used if n in citation_map]
    charts = [
        piece["chart"] for piece in evidence if piece.get("chart")
    ]
    confidence = (state.get("verification") or {}).get("confidence")
    return {"answer": answer, "citations": citations, "charts": charts, "confidence": confidence}


def build_graph():
    graph = StateGraph(InvestigationState)
    graph.add_node("transcribe", transcribe_node)
    graph.add_node("classify", classify_node)
    graph.add_node("rag", rag_node)
    graph.add_node("data", data_node)
    graph.add_node("vision", vision_node)
    graph.add_node("fuse", fuse_node)
    graph.add_node("verify", verify_node)
    graph.add_node("generate", generate_node)

    graph.add_edge(START, "transcribe")
    graph.add_edge("transcribe", "classify")
    graph.add_conditional_edges(
        "classify", _route_capabilities, ["rag", "data", "vision", "fuse"]
    )
    graph.add_edge("rag", "fuse")
    graph.add_edge("data", "fuse")
    graph.add_edge("vision", "fuse")
    graph.add_edge("fuse", "verify")
    graph.add_conditional_edges("verify", _route_verify, ["rag", "generate"])
    graph.add_edge("generate", END)
    return graph.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
