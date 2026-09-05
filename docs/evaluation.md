# Evaluation

## Test Categories

| Category | Count | Description |
|----------|-------|-------------|
| direct | 5 | Simple factual retrieval |
| multi_hop | 5 | Cross-document reasoning |
| table | 5 | Structured data queries |
| handwriting | 5 | OCR + handwriting recognition |
| vision | 5 | Image/chart analysis |
| audio | 5 | Speech transcription |
| unanswerable | 5 | Questions with no evidence |
| ambiguous | 5 | Open-ended questions |
| retrieval_heavy | 5 | Specific page/row/datum |
| mixed | 5 | Multi-modal combinations |
| data_analysis | 10 | Pandas operations |
| conversational | 5 | Follow-up / context-dependent |

The repository contains seed cases for the benchmark. The live evaluation
dataset is configurable: cases can be seeded from the JSON file or generated
from recent investigations in Settings. The API reports the actual number of
cases in each run; do not assume a fixed total after adding or removing cases.

## Metrics

| Metric | Definition |
|--------|------------|
| Recall@K | Fraction of relevant chunks in top-K results |
| MRR | Mean Reciprocal Rank of first relevant result |
| nDCG@K | Normalized Discounted Cumulative Gain |
| Correctness | LLM-graded match to expected answer |
| Faithfulness | LLM-graded citation support (no hallucination) |
| Citation Accuracy | Fraction of expected sources cited |

## Retrieval Comparison

Run the same eval cases with different modes:

```
vector only          → baseline
hybrid               → + lexical
hybrid + rerank      → + LLM reranking
hybrid + rerank + mq → + multi-query generation
```

## Running

```bash
# Seed cases
uv run python scripts/seed_eval_cases.py

# Run evaluation via API
POST /api/evaluation/run
{
  "workspace_id": "...",
  "retrieval_mode": "hybrid_rerank"
}

# View results
GET /api/evaluation/runs?workspace_id=...
```
