import asyncio
import logging
import re
from pathlib import Path
from typing import Any

import httpx
from langgraph.graph import END, START, StateGraph

from app.agents import events
from app.agents.state import InvestigationState
from app.core.db import get_db
from app.data.analysis import analyze_dataset
from app.providers.base import TaskType
from app.providers.registry import get_model_router
from app.rag.query import generate_multi_queries, rewrite_query
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

GENERATE_SYSTEM = """You are Emmaus AI, a rigorous multimodal analyst.

Rules:
- Ground every factual claim in the numbered evidence below and cite as [1], [2]...
- Combine document evidence, dataset analysis results, image observations and transcripts when available.
- Include key numbers exactly as they appear in the evidence.
- If evidence is insufficient for part of the question, say so explicitly instead of guessing.
- Be direct and structured. Use short paragraphs or bullets.
- Use clean, restrained Markdown and ordinary hyphens. Avoid decorative Unicode symbols and em dashes.
- State the answer once. Do not add a separate section that repeats the same answer.
- When a chart spec accompanies the answer, describe its key insights in words and point at the chart. Never paste code blocks or data-URI image markdown - the chart renders itself.
- End with a line: "Confidence: <low|medium|high> - <one short reason>"."""


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
        media = await db.media_assets.find_one(
            {"_id": audio_id, "workspace_id": state["workspace_id"]}
        )
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
    # Attached photos must be visible to the classifier, otherwise a
    # photo-only question routes nowhere and ends in "no evidence".
    attached_images: list[str] = []
    attachment_ids = state.get("attachment_ids") or []
    if attachment_ids:
        try:
            media_cursor = db.media_assets.find(
                {
                    "_id": {"$in": attachment_ids},
                    "workspace_id": state["workspace_id"],
                    "kind": "image",
                },
                {"_id": 1, "filename": 1},
            )
            async for m in media_cursor:
                attached_images.append(m.get("filename") or "image")
        except Exception as exc:
            logger.warning("classify attachment lookup failed: %s", exc)
    for name in attached_images:
        sources.append(f"- image: {name} (attached photo - analyze it directly)")
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
    if attached_images and "vision" not in capabilities:
        capabilities.append("vision")
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
        ctx=ctx,
    )

    if len(chunks) < 3 and state.get("retry_count", 0) == 0:
        alt_queries = await generate_multi_queries(
            rewritten, ctx=ctx, num_queries=2
        )
        seen_ids = {c.chunk_id for c in chunks}
        for alt_q in alt_queries:
            alt_chunks = await retriever.retrieve(
                state["workspace_id"],
                alt_q,
                mode=mode,
                document_ids=attachment_docs or None,
                ctx=ctx,
            )
            for c in alt_chunks:
                if c.chunk_id not in seen_ids:
                    chunks.append(c)
                    seen_ids.add(c.chunk_id)

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


_DATASET_WAIT_SECONDS = 15

async def data_node(state: InvestigationState) -> dict:
    db = get_db()
    ctx = events.get_run_ctx()
    attachment_ids = state.get("attachment_ids") or []

    async def _ready_targets() -> list[dict]:
        found: list[dict] = []
        cursor = db.datasets.find({"workspace_id": state["workspace_id"], "status": "ready"})
        async for dataset in cursor:
            if not attachment_ids or dataset["_id"] in attachment_ids:
                found.append(dataset)
        return found[:3]

    targets = await _ready_targets()
    if not targets:
        # Datasets index asynchronously after upload; a question asked
        # immediately can arrive while they are still "processing". Wait
        # briefly instead of answering with no data.
        processing = await db.datasets.count_documents(
            {"workspace_id": state["workspace_id"], "status": "processing"}
        )
        if processing:
            events.emit(
                {"type": "node", "node": "data", "detail": "waiting for dataset indexing"}
            )
            for _ in range(_DATASET_WAIT_SECONDS):
                await asyncio.sleep(1)
                targets = await _ready_targets()
                if targets:
                    break
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


_LOCAL_MEDIA_DIR = Path("media")
_VISION_ON_DEMAND_MAX = 3

_IMAGE_MIMES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def _mime_for_image(filename: str) -> str:
    lower = (filename or "").lower()
    for ext, mime in _IMAGE_MIMES.items():
        if lower.endswith(ext):
            return mime
    return "image/jpeg"


async def _load_media_bytes(media: dict, filename: str) -> tuple[bytes, str] | None:
    """Load raw image bytes for on-demand analysis (local disk or remote URL).

    Local lookup order: persisted bytes_path, then the stored URL (which
    carries the true on-disk filename), then the legacy public_id derivation.
    """
    mode = media.get("storage_mode") or media.get("mode") or ""
    url = media.get("url") or ""
    public_id = media.get("public_id") or ""
    candidates: list[Path] = []
    raw_path = media.get("bytes_path")
    if raw_path:
        candidates.append(Path(raw_path))
        stripped = str(raw_path).replace("\\", "/")
        if stripped.startswith("media/"):
            candidates.append(_LOCAL_MEDIA_DIR / stripped[len("media/"):])
    if mode == "local" or url.startswith("/media/"):
        if url.startswith("/media/"):
            candidates.append(_LOCAL_MEDIA_DIR / url[len("/media/"):])
        elif public_id:
            rel = public_id.split("/", 1)[1] if "/" in public_id else public_id
            candidates.append(_LOCAL_MEDIA_DIR / rel)
    for path in candidates:
        try:
            if path.is_file():
                return path.read_bytes(), _mime_for_image(filename)
        except OSError as exc:
            logger.warning("vision on-demand local read failed: %s", exc)
            return None
    if url.startswith("http"):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                mime = response.headers.get("content-type", "").split(";")[0].strip()
                return response.content, mime or _mime_for_image(filename)
        except Exception as exc:
            logger.warning("vision on-demand remote fetch failed: %s", exc)
            return None
    return None


async def _analyze_image_on_demand(
    db, collection: str, record_id: str, media: dict, filename: str
) -> dict | None:
    """Run vision analysis now for images whose upload-time analysis is missing,
    and persist it so the next question is instant."""
    from app.vision.analyzer import analyze_image

    loaded = await _load_media_bytes(media, filename)
    if not loaded:
        return None
    data, mime = loaded
    try:
        analysis = await analyze_image(data, mime)
    except Exception as exc:
        logger.warning("vision on-demand analysis failed: %s", exc)
        return None
    if not analysis:
        return None
    try:
        await db[collection].update_one({"_id": record_id}, {"$set": {"analysis": analysis}})
    except Exception as exc:
        logger.warning("vision analysis persist failed: %s", exc)
    return analysis


async def vision_node(state: InvestigationState) -> dict:
    db = get_db()
    attachment_ids = state.get("attachment_ids") or []
    results = []
    ws_id = state["workspace_id"]
    on_demand_used = 0
    if attachment_ids:
        for attachment_id in attachment_ids:
            media = await db.media_assets.find_one(
                {"_id": attachment_id, "kind": "image", "workspace_id": ws_id}
            )
            if media:
                analysis = media.get("analysis")
                if not analysis and on_demand_used < _VISION_ON_DEMAND_MAX:
                    events.emit(
                        {"type": "node", "node": "vision", "detail": "analyzing image now"}
                    )
                    analysis = await _analyze_image_on_demand(
                        db, "media_assets", media["_id"], media,
                        media.get("filename", "image"),
                    )
                    if analysis:
                        on_demand_used += 1
                if analysis:
                    results.append(
                        {
                            "source_name": media.get("filename", "image"),
                            "description": analysis.get("description", ""),
                            "extracted_text": analysis.get("extracted_text", ""),
                            "is_handwritten": analysis.get("is_handwritten", False),
                            "key_observations": analysis.get("key_observations", []),
                            "confidence": analysis.get("confidence", 0.0),
                            "media_url": media.get("url"),
                        }
                    )
                    continue
            document = await db.documents.find_one(
                {"_id": attachment_id, "source_type": "image", "workspace_id": ws_id}
            )
            if document:
                analysis = document.get("analysis")
                if not analysis and on_demand_used < _VISION_ON_DEMAND_MAX:
                    events.emit(
                        {"type": "node", "node": "vision", "detail": "analyzing image now"}
                    )
                    analysis = await _analyze_image_on_demand(
                        db, "documents", document["_id"],
                        document.get("media") or {}, document["filename"],
                    )
                    if analysis:
                        on_demand_used += 1
                if analysis:
                    results.append(
                        {
                            "source_name": document["filename"],
                            "description": analysis.get("description", ""),
                            "extracted_text": analysis.get("extracted_text", ""),
                            "is_handwritten": analysis.get("is_handwritten", False),
                            "key_observations": analysis.get("key_observations", []),
                            "confidence": analysis.get("confidence", 0.0),
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
    ws_id = state["workspace_id"]
    doc_media: dict[str, str | None] = {}
    unique_doc_ids = list({chunk.get("document_id") for chunk in chunks if chunk.get("document_id")})
    if unique_doc_ids:
        async for document in db.documents.find(
            {"_id": {"$in": unique_doc_ids}, "workspace_id": ws_id}, {"_id": 1, "media": 1}
        ):
            doc_media[document["_id"]] = (document.get("media") or {}).get("url")
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
    # When a chart rides along, fenced code blocks are pure noise (the viewer
    # renders the chart): suppress them from the live token stream, unless the
    # user explicitly asked for code.
    q_lower = (state.get("question") or "").lower()
    strip_code = any(piece.get("chart") for piece in evidence) and not any(
        w in q_lower
        for w in ("code", "python", "script", "snippet", "matplotlib", "plotly", "seaborn")
    )
    in_fence = False
    line_buf = ""

    async def _emit(text: str) -> None:
        nonlocal answer
        answer += text
        events.emit({"type": "token", "text": text})

    try:
        async for piece in router.stream(
            messages, task=TaskType.REASONING, temperature=0.2, max_tokens=3000, ctx=ctx
        ):
            if not strip_code:
                await _emit(piece)
                continue
            line_buf += piece
            while "\n" in line_buf:
                line, line_buf = line_buf.split("\n", 1)
                if "```" in line:
                    in_fence = not in_fence
                    continue
                if in_fence:
                    continue
                await _emit(line + "\n")
        if strip_code and line_buf and not in_fence:
            await _emit(line_buf)
    except Exception as exc:
        logger.error("generation failed: %s", exc)
        answer = (
            "I could not generate a final answer due to a model provider error. "
            f"Please try again. (Error: {str(exc)[:150]})"
        )
        events.emit({"type": "token", "text": answer})
    used = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)})
    citations = [citation_map[n] for n in used if n in citation_map]
    if not citations:
        # The model sometimes answers without [N] markers even though it
        # generated from retrieved evidence. Fall back to the top retrieved
        # sources so the Sources button is never empty after a grounded answer.
        seen_docs: set[str] = set()
        for piece in evidence:
            citation = piece.get("citation")
            if not citation:
                continue
            doc_id = citation.get("document_id") or citation.get("document_name")
            if doc_id in seen_docs:
                continue
            seen_docs.add(doc_id)
            citations.append(citation)
            if len(citations) >= 3:
                break
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
