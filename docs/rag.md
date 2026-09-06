# RAG Pipeline

## Retrieval Modes

| Mode | Description |
|------|-------------|
| `vector` | Atlas `$vectorSearch` only |
| `hybrid` | Vector + lexical fused via RRF |
| `hybrid_rerank` | Hybrid + LLM reranking (default) |

## Pipeline

```
Question
  │
  ├── Rewrite Query (LLM)
  │     └── Resolve pronouns, expand abbreviations
  │
  ├── Multi-Query Generation (if <3 results)
  │     └── 2 alternative search queries
  │
  ├── Vector Search (Atlas $vectorSearch)
  │     └── Jina Embeddings v5 Omni Small (1024D) → cosine similarity
  │
  ├── Lexical Search (Atlas $search)
  │     └── BM25 text matching
  │
  ├── RRF Fusion (k=60)
  │     └── Reciprocal Rank Fusion of both result sets
  │
   ├── LLM Reranking (optional)
    │     └── Ollama gpt-oss:120b (Groq gpt-oss:20b fallback) scores relevance 0-10
  │
  └── Top-K Selection (default: 6)
```

## Embedding Backends

| Backend | Provider | Dimensions | Use Case |
|---------|----------|------------|----------|
| Jina v5 Omni Small | Jina AI | 1024 | Primary (production) |
| Ollama | nomic-embed-text | 768 | Self-hosted fallback |
| Local | all-MiniLM-L6-v2 | 384 | Offline/development |
| Mock | Deterministic hash | 768 | Testing only |

## Chunking Strategy

- **Heading-aware**: Splits on markdown `#` headings
- **List extraction**: Separates bullet lists into dedicated chunks
- **Parent context**: Each chunk stores its section heading + preview
- **Overlap**: 150 chars overlap between consecutive chunks
- **Min size**: 40 chars (smaller fragments discarded)

## Atlas Indexes

- `vector_index`: vectorSearch on `embedding` field, filtered by workspace_id
- `lexical_index`: search on `content` field, filtered by workspace_id
