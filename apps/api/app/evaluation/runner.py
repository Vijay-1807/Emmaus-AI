import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from app.core.db import get_db
from app.evaluation.metrics import citation_accuracy, grade_answer, mrr, ndcg_at_k, recall_at_k
from app.providers.base import RunContext, TaskType
from app.providers.registry import get_model_router
from app.rag.retriever import get_retriever

logger = logging.getLogger("vedax.evaluation")

ANSWER_SYSTEM = """You are a precise analyst. Answer ONLY from the provided evidence.
Cite evidence as [1], [2]. If the evidence does not contain the answer, say "Insufficient evidence"."""


def now() -> datetime:
    return datetime.now(timezone.utc)


async def load_cases(case_ids: list[str], categories: list[str], limit: int) -> list[dict]:
    db = get_db()
    query: dict = {}
    if case_ids:
        query["_id"] = {"$in": case_ids}
    if categories:
        query["category"] = {"$in": categories}
    cursor = db.evaluation_cases.find(query).limit(limit)
    return [case async for case in cursor]


async def create_and_run(
    workspace_id: str,
    retrieval_mode: str,
    case_ids: list[str],
    categories: list[str],
    max_cases: int,
) -> dict:
    db = get_db()
    run = {
        "_id": uuid.uuid4().hex,
        "workspace_id": workspace_id,
        "config": {
            "retrieval_mode": retrieval_mode,
            "case_ids": case_ids,
            "categories": categories,
        },
        "status": "running",
        "num_cases": 0,
        "results": [],
        "created_at": now(),
    }
    await db.evaluation_runs.insert_one(run)
    asyncio.create_task(
        _execute_run(run["_id"], workspace_id, retrieval_mode, case_ids, categories, max_cases)
    )
    return run


async def _execute_run(
    run_id: str,
    workspace_id: str,
    retrieval_mode: str,
    case_ids: list[str],
    categories: list[str],
    max_cases: int,
) -> None:
    db = get_db()
    try:
        cases = await load_cases(case_ids, categories, max_cases)
        if not cases:
            await db.evaluation_runs.update_one(
                {"_id": run_id},
                {"$set": {"status": "failed", "results": [], "error": "no evaluation cases found"}},
            )
            return
        retriever = get_retriever()
        router = get_model_router()
        results = []
        for case in cases:
            result = await _evaluate_case(case, workspace_id, retrieval_mode, retriever, router)
            results.append(result)
        recall_scores = [r["recall_at_5"] for r in results if r["recall_at_5"] is not None]
        mrr_scores = [r["mrr"] for r in results if r["mrr"] is not None]
        correctness_scores = [r["correctness"] for r in results if r["correctness"] is not None]
        faithfulness_scores = [r["faithfulness"] for r in results if r["faithfulness"] is not None]
        citation_scores = [r["citation_accuracy"] for r in results if r["citation_accuracy"] is not None]
        latencies = [r["latency_ms"] for r in results]

        def avg(values: list[float]) -> float | None:
            return round(sum(values) / len(values), 4) if values else None

        await db.evaluation_runs.update_one(
            {"_id": run_id},
            {
                "$set": {
                    "status": "completed",
                    "num_cases": len(results),
                    "results": results,
                    "retrieval_recall_at_5": avg(recall_scores),
                    "retrieval_mrr": avg(mrr_scores),
                    "answer_correctness": avg(correctness_scores),
                    "faithfulness": avg(faithfulness_scores),
                    "citation_accuracy": avg(citation_scores),
                    "avg_latency_ms": avg(latencies),
                }
            },
        )
        logger.info("evaluation run %s completed: %s cases", run_id, len(results))
    except Exception as exc:
        logger.error("evaluation run failed: %s", exc, exc_info=True)
        await db.evaluation_runs.update_one(
            {"_id": run_id}, {"$set": {"status": "failed", "error": str(exc)[:500]}}
        )


async def _evaluate_case(
    case: dict, workspace_id: str, retrieval_mode: str, retriever, router
) -> dict:
    started = time.perf_counter()
    question = case["question"]
    expected_docs = case.get("expected_document_names") or []
    ctx = RunContext(workspace_id=workspace_id)

    chunks = await retriever.retrieve(workspace_id, question, mode=retrieval_mode, top_k=6)
    retrieved_ids = [c.chunk_id for c in chunks]
    retrieved_doc_names = [c.document_name for c in chunks]

    recall = recall_at_k(retrieved_ids, case.get("expected_chunk_ids", []), k=5)
    mean_reciprocal = mrr(retrieved_ids, case.get("expected_chunk_ids", []))
    ndcg = ndcg_at_k(retrieved_ids, case.get("expected_chunk_ids", []), k=5)

    context = "\n\n".join(
        f"[{i + 1}] ({c.document_name} p.{c.page})\n{c.content[:800]}" for i, c in enumerate(chunks)
    )
    answer = ""
    citations = []
    if chunks:
        try:
            result = await router.complete(
                [
                    {"role": "system", "content": ANSWER_SYSTEM},
                    {"role": "user", "content": f"Question: {question}\n\nEvidence:\n{context}"},
                ],
                task=TaskType.REASONING,
                ctx=ctx,
            )
            answer = result.text
        except Exception as exc:
            answer = f"(generation failed: {exc})"
    else:
        answer = "Insufficient evidence"

    import re

    used = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)})
    citations = [
        {"document_name": chunks[n - 1].document_name, "chunk_id": chunks[n - 1].chunk_id}
        for n in used
        if 0 < n <= len(chunks)
    ]
    graded = await grade_answer(question, case.get("expected_answer", ""), answer, citations, ctx)
    citation_score = citation_accuracy(answer, citations, expected_docs or None)

    return {
        "case_id": case["_id"],
        "question": question,
        "category": case.get("category", "general"),
        "retrieved_docs": retrieved_doc_names[:5],
        "recall_at_5": round(recall, 4) if case.get("expected_chunk_ids") else None,
        "mrr": round(mean_reciprocal, 4) if case.get("expected_chunk_ids") else None,
        "ndcg_at_5": round(ndcg, 4) if case.get("expected_chunk_ids") else None,
        "correctness": graded["correctness"],
        "faithfulness": graded["faithfulness"],
        "citation_accuracy": round(citation_score, 4) if expected_docs else None,
        "answer_preview": answer[:300],
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }


async def list_runs(workspace_id: str, limit: int = 20) -> list[dict]:
    db = get_db()
    query = {"workspace_id": workspace_id}
    cursor = db.evaluation_runs.find(query).sort("created_at", -1).limit(limit)
    return [run async for run in cursor]


async def get_run(run_id: str, workspace_id: str) -> dict | None:
    db = get_db()
    return await db.evaluation_runs.find_one({"_id": run_id, "workspace_id": workspace_id})


async def list_cases(limit: int = 200) -> list[dict]:
    db = get_db()
    cursor = db.evaluation_cases.find({}).limit(limit)
    return [case async for case in cursor]


async def seed_cases(cases: list[dict]) -> int:
    db = get_db()
    inserted = 0
    for case in cases:
        document = {
            "_id": case.get("id") or uuid.uuid4().hex,
            "question": case["question"],
            "expected_answer": case.get("expected_answer", ""),
            "expected_document_names": case.get("expected_document_names", []),
            "expected_chunk_ids": case.get("expected_chunk_ids", []),
            "category": case.get("category", "general"),
            "created_at": now(),
        }
        try:
            await db.evaluation_cases.insert_one(document)
            inserted += 1
        except Exception:
            continue
    return inserted
