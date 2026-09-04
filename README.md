# Emmaus AI

**Multimodal Agentic Knowledge & Analysis Platform**

Upload documents, datasets, images, handwritten pages, or audio. Ask a question. Emmaus AI intelligently combines RAG, data analysis, vision/OCR, and agentic reasoning to produce verified, cited answers, charts, and reports.

**No login required.** Anonymous workspaces with browser-session persistence.

## 60-Second Demo

```
1. Open vedaX.ai
2. Upload: quarterly_report.pdf, sales.xlsx, handwritten_notes.jpg
3. Ask: "Why did Q3 revenue decline?"
4. Watch:
   - System classifies: rag + data capabilities needed
   - RAG retrieves 6 relevant passages (vector + lexical + rerank)
   - Data agent analyzes sales.xlsx (group by region, compute trend)
   - Vision reads handwritten notes (OCR + structured extraction)
   - Verifier confirms evidence is sufficient
   - Answer streams in with [1], [2] citations and a revenue chart
5. Ask follow-up: "Which region contributed most?"
   - Multi-query generation finds better passages
   - Conversation history maintained
```

## Architecture

```
                    USER
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
        Web         Camera      Telegram
     (Next.js)    (capture)      (bot)
          │           │           │
          └───────────┼───────────┘
                      ▼
                   FastAPI
                      │
                  LangGraph
                      │
       ┌──────────────┼──────────────┐
       ▼              ▼              ▼
      RAG          Data Agent     Vision/Audio
       │              │              │
  Hybrid +        Typed 7-Op     Gemma 4 Vision
  Reranking       Interpreter    Whisper STT
       │              │              │
       └──────────────┼──────────────┘
                      ▼
               Evidence Fusion
                      │
               Evidence Verifier
                      │
                  Model Router
             ┌────────┼────────┐
             ▼        ▼        ▼
          Cerebras   Groq    Ollama
          Primary   2ndary  3rdary
             │
             ▼
        Answer / Chart / Report
             │
     ┌───────┼─────────┐
     ▼       ▼         ▼
 MongoDB  Cloudinary  Langfuse
 Atlas
```

## LangGraph Pipeline (8 Nodes)

```
START
  │
  ▼
transcribe ──→ classify ──→ [rag, data, vision] (parallel)
                                 │
                                 ▼
                              fuse
                                 │
                                 ▼
                              verify ──→ (retry if insufficient)
                                 │
                                 ▼
                              generate ──→ END
```

| Node | Purpose |
|------|---------|
| `transcribe` | Audio → text (Sarvam → Deepgram → Groq Whisper) |
| `classify` | LLM determines needed capabilities (rag/data/vision) |
| `rag` | Multi-query retrieval + reranking |
| `data` | Typed pandas operations on datasets |
| `vision` | Gemma 4 image analysis + OCR |
| `fuse` | Combine all evidence into unified context |
| `verify` | LLM checks evidence sufficiency; retry once if not |
| `generate` | Stream final answer with citations and charts |

## Model Routing

Fallback order: **Cerebras → Groq → Ollama → Mock**

| Task | Primary | 2nd | 3rd | Model |
|------|---------|-----|-----|-------|
| Reasoning | Cerebras | Groq | Ollama | gpt-oss-120b |
| Classification | Cerebras | Groq | Ollama | gpt-oss-120b |
| Query Rewrite | Cerebras | Groq | Ollama | gpt-oss-120b |
| Reranking | Cerebras | Groq | Ollama | gpt-oss-120b |
| Verification | Cerebras | Groq | Ollama | gpt-oss-120b |
| Vision | Groq (qwen3.6-27b) | Ollama (gemma4:31b) | Mock | qwen/qwen3.6-27b |
| Embedding | Gemini 001 | Ollama | Local | gemini-embedding-001 (3072d) |
| Speech-to-Text | Deepgram | Sarvam | Groq | nova-3 / saaras:v4 / whisper-large-v3-turbo |

**STT chain**: Sarvam Saaras v4 (best for Indian languages) → Deepgram Nova-3 (general) → Groq Whisper (fast/cheap)

## RAG Pipeline

```
Question
  │
  ├── Rewrite Query (LLM)
  │     └── Resolve pronouns, expand abbreviations
  │
  ├── Multi-Query Generation (if <3 results)
  │     └── 2 alternative search queries via LLM
  │
  ├── Vector Search (Atlas $vectorSearch)
  │     └── Gemini Embedding 001 (3072d) → cosine similarity
  │
  ├── Lexical Search (Atlas $search)
  │     └── BM25 text matching
  │
  ├── RRF Fusion (k=60)
  │     └── Reciprocal Rank Fusion of both result sets
  │
  ├── LLM Reranking
  │     └── Groq fast model scores relevance 0-10
  │
  └── Top-K Selection (default: 6)
```

## Data Analysis (Typed Op Plan)

No `exec()`. 7 allow-listed operations:

| Operation | Description |
|-----------|-------------|
| `filter` | Filter rows by field value |
| `group_by` | Group + aggregate (sum, avg, count, min, max) |
| `sort` | Sort by field (asc/desc) |
| `select` | Choose specific fields |
| `compute` | Calculate derived fields |
| `compare_periods` | Compare two time periods |
| `detect_anomaly` | Detect outliers in numeric data |

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind CSS 4, Zustand |
| Backend | FastAPI, Python 3.11+, Pydantic, PyMongo Async |
| Orchestration | LangGraph (8-node conditional pipeline) |
| Database | MongoDB Atlas (Vector Search + Atlas Search) |
| Media | Cloudinary (or local) |
| Models | Groq (gpt-oss-120b, gpt-oss-20b, qwen3.6-27b vision, whisper-turbo), Ollama Cloud (gpt-oss:120b, gemma4:31b fallback), Jina (embeddings-1024d) |
| Observability | Langfuse (traces, generation spans, events) |
| Auth | JWT (HS256) with rotating refresh tokens |
| Background Jobs | MongoDB-backed durable queue + worker process |

## Deployment

| Component | Target | Config |
|-----------|--------|--------|
| Frontend | Vercel | `apps/web/vercel.json` |
| API | Render (Docker) | `render.yaml`, `infra/docker/Dockerfile.api` |
| Worker | Render (Docker) | `infra/docker/Dockerfile.worker` |
| Database | MongoDB Atlas (M0+) | Vector + lexical search indexes |
| Media | Cloudinary | |
| Observability | Langfuse Cloud | |

## Quick Start

### Backend
```bash
cd apps/api
cp .env.example .env
uv sync
uv run uvicorn app.main:app --reload
```

### Frontend
```bash
cd apps/web
npm install
npm run dev
```

### Worker (background jobs)
```bash
cd apps/api
uv run python -m app.worker.main
```

### Docker Compose (full stack)
```bash
docker-compose up
```

## Key Features

- **Multi-query retrieval**: Auto-generates alternative search queries when initial results are sparse
- **Hybrid search**: Vector (Atlas vectorSearch) + lexical (Atlas search) fused via RRF, then LLM-reranked
- **Typed data analysis**: No `exec()` — 7 safe operations executed in a sandboxed interpreter
- **Vision pipeline**: Region detection, content type classification, structured OCR
- **Handwriting recognition**: Dedicated handwriting detection and extraction
- **Audio transcription**: Voice input via Groq Whisper
- **Camera capture**: Direct camera input from browser
- **Evidence verification**: LLM-based evidence sufficiency check with retry loop
- **Streaming**: SSE-based real-time response streaming
- **Observability**: Full Langfuse tracing across retrieval, reranking, and evaluation
- **Job queue**: MongoDB-backed durable queue with worker process
- **Telegram bot**: Full Telegram integration with webhook validation
- **75 evaluation cases**: 12 categories (direct, multi-hop, table, handwriting, vision, audio, unanswerable, ambiguous, retrieval, mixed, data-analysis, conversational)

## Resilience

The system handles failures gracefully:

- **Provider timeout**: Falls back through Ollama → Groq → Cerebras → Mock
- **Atlas unavailable**: Returns empty results (no crash)
- **Embedding failure**: Fails open in test, fails closed in production
- **OCR failure**: Returns partial analysis with confidence score
- **Malformed PDF**: Skips file, logs error, continues batch
- **Large uploads**: Chunked upload with streaming validation
- **Worker restart**: Durable job queue survives restarts
- **Duplicate webhooks**: Idempotent handling

See `tests/test_resilience.py` for 40+ resilience test cases.

## Repository Structure

```
        Emmaus-AI/
├── apps/
│   ├── api/                 # FastAPI backend
│   │   ├── app/
│   │   │   ├── api/         # REST endpoints
│   │   │   ├── agents/      # LangGraph orchestration
│   │   │   ├── rag/         # Retrieval, embeddings, reranking
│   │   │   ├── vision/      # Vision/OCR analysis
│   │   │   ├── audio/       # Speech-to-text
│   │   │   ├── data/        # Structured data analysis
│   │   │   ├── providers/   # Model router
│   │   │   ├── ingestion/   # Document parsing, chunking, indexing
│   │   │   ├── services/    # Business logic, job queue
│   │   │   ├── evaluation/  # RAG/agent benchmarks
│   │   │   ├── observability/
│   │   │   ├── integrations/
│   │   │   └── worker/      # Background job worker
│   │   ├── scripts/         # Setup scripts
│   │   ├── tests/
│   │   └── pyproject.toml
│   └── web/                 # Next.js frontend
│       ├── app/             # 10 routes
│       ├── components/      # Camera, Sidebar, AppLayout
│       ├── lib/             # api, store, types, utils
│       └── package.json
├── evaluation/
│   └── datasets/            # 75 eval cases
├── docs/                    # architecture, rag, evaluation, model-routing
├── infra/docker/            # Dockerfiles
├── docker-compose.yaml      # Local dev stack
└── render.yaml              # Render deployment
```

## License

MIT — see [LICENSE](LICENSE)
