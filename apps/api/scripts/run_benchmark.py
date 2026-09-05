"""Run the configured Emmaus evaluation benchmark and produce metrics report.

Usage:
    cd apps/api
    uv run python scripts/run_benchmark.py [--mode hybrid_rerank] [--output benchmark_results.json]

Requires: MongoDB Atlas with data, Gemini/Ollama/Groq configured.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from statistics import mean, median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.db import connect_db, close_db
from app.evaluation.runner import load_cases, _evaluate_case
from app.rag.retriever import get_retriever
from app.providers.registry import get_model_router


def percentile(values: list[float], p: float) -> float:
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * p / 100
    f = int(k)
    c = f + 1
    if c >= len(sorted_v):
        return sorted_v[-1]
    return sorted_v[f] + (k - f) * (sorted_v[c] - sorted_v[f])


async def main():
    parser = argparse.ArgumentParser(description="Run Emmaus benchmark")
    parser.add_argument("--mode", default="hybrid_rerank", help="retrieval mode")
    parser.add_argument("--output", default="benchmark_results.json", help="output file")
    parser.add_argument("--categories", nargs="*", help="filter categories")
    parser.add_argument("--max-cases", type=int, default=200, help="max cases to run")
    args = parser.parse_args()

    await connect_db()
    retriever = get_retriever()
    router = get_model_router()

    cases = await load_cases([], args.categories or [], args.max_cases)
    print(f"Running {len(cases)} evaluation cases in '{args.mode}' mode...")

    results = []
    started = time.perf_counter()
    token_usage = {"input": 0, "output": 0}
    fallback_count = 0
    total_llm_calls = 0

    for i, case in enumerate(cases):
        case_started = time.perf_counter()
        print(f"  [{i+1}/{len(cases)}] {case.get('category', '?')}: {case['question'][:60]}...")
        try:
            result = await _evaluate_case(
                case, "benchmark", args.mode, retriever, router
            )
            results.append(result)
            latency = time.perf_counter() - case_started
            print(f"    -> {latency:.1f}s, correctness={result.get('correctness', 'N/A')}")
        except Exception as exc:
            print(f"    -> FAILED: {exc}")
            results.append({
                "case_id": case["_id"],
                "question": case["question"],
                "category": case.get("category", "general"),
                "error": str(exc)[:300],
                "latency_ms": round((time.perf_counter() - case_started) * 1000, 1),
            })

    total_time = time.perf_counter() - started

    # Compute aggregate metrics
    valid = [r for r in results if "error" not in r]
    latencies = [r["latency_ms"] for r in results]

    def safe_mean(key):
        vals = [r[key] for r in valid if r.get(key) is not None]
        return round(mean(vals), 4) if vals else None

    report = {
        "benchmark": "vedax-75",
        "mode": args.mode,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {
            "total_cases": len(results),
            "completed": len(valid),
            "failed": len(results) - len(valid),
            "total_time_s": round(total_time, 1),
            "avg_latency_ms": safe_mean("latency_ms"),
            "p50_latency_ms": round(percentile(latencies, 50), 1) if latencies else None,
            "p95_latency_ms": round(percentile(latencies, 95), 1) if latencies else None,
        },
        "retrieval": {
            "recall_at_5": safe_mean("recall_at_5"),
            "mrr": safe_mean("mrr"),
            "ndcg_at_5": safe_mean("ndcg_at_5"),
        },
        "answer_quality": {
            "correctness": safe_mean("correctness"),
            "faithfulness": safe_mean("faithfulness"),
            "citation_accuracy": safe_mean("citation_accuracy"),
        },
        "by_category": {},
        "results": results,
    }

    # Per-category breakdown
    categories = set(r.get("category", "general") for r in results)
    for cat in sorted(categories):
        cat_results = [r for r in valid if r.get("category") == cat]
        if not cat_results:
            continue
        cat_latencies = [r["latency_ms"] for r in cat_results]
        report["by_category"][cat] = {
            "count": len(cat_results),
            "correctness": safe_mean("correctness") if any(r.get("correctness") is not None for r in cat_results) else None,
            "faithfulness": safe_mean("faithfulness") if any(r.get("faithfulness") is not None for r in cat_results) else None,
            "avg_latency_ms": round(mean(cat_latencies), 1),
        }

    output_path = Path(args.output)
    output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nBenchmark complete: {len(valid)}/{len(results)} cases succeeded")
    print(f"Total time: {total_time:.1f}s")
    print(f"Results saved to {output_path}")

    # Print summary
    print("\n=== BENCHMARK SUMMARY ===")
    print(f"Mode: {args.mode}")
    print(f"Cases: {len(valid)}/{len(results)}")
    print(f"Avg latency: {report['summary']['avg_latency_ms']}ms")
    print(f"P50 latency: {report['summary']['p50_latency_ms']}ms")
    print(f"P95 latency: {report['summary']['p95_latency_ms']}ms")
    print(f"Recall@5: {report['retrieval']['recall_at_5']}")
    print(f"MRR: {report['retrieval']['mrr']}")
    print(f"nDCG@5: {report['retrieval']['ndcg_at_5']}")
    print(f"Correctness: {report['answer_quality']['correctness']}")
    print(f"Faithfulness: {report['answer_quality']['faithfulness']}")
    print(f"Citation accuracy: {report['answer_quality']['citation_accuracy']}")

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
