# VedaX AI

**Multimodal Agentic Knowledge & Analysis Platform**

Upload documents, datasets, images, handwritten pages, or audio; ask a question; the system intelligently combines RAG, data analysis, vision/OCR, and agentic reasoning to produce verified, cited answers, charts, and reports.

## Architecture

```
┌─────────────────┐     SSE/REST      ┌─────────────────┐
│   Next.js 15    │ ◄────────────────► │    FastAPI      │
│   (Vercel)      │                    │   (Render)      │
└─────────────────┘                    └────────┬────────┘
                                                │
                    ┌───────────────────────────┼───────────────────────────┐
                    ▼                           ▼                           ▼
             Document/RAG                 Data Agent                   Vision/Audio
              (MongoDB Atlas)              (Pandas)                (Gemma/OCR/STT)
              Vector + Lexical
              RRF + Rerank
                    │                           │                           │
                    └───────────────────────────┼───────────────────────────┘
                                                ▼
                                         Evidence Fusion
                                                │
                                            Verification
                                                │
                                            Model Router
                                 ┌──────────────┼──────────────┐
                                 ▼              ▼              ▼
                            Ollama           Groq          Cerebras
                            Primary          Fast          Optional
```

## Stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind CSS 4, Zustand |
| Backend | FastAPI, Python 3.11+, Pydantic, PyMongo Async |
| Orchestration | LangGraph (transcribe → classify → rag/data/vision → fuse → verify → generate) |
| Database | MongoDB Atlas (Vector Search + Atlas Search) |
| Media | Cloudinary (or local) |
| Models | Ollama Cloud (gpt-oss:120b, gemma4:31b), Groq (llama-3.1-8b-instant, llama-3.3-70b-versatile, whisper-large-v3-turbo), Cerebras (optional), Gemini Embedding 001 (3072d) |
| Observability | Langfuse |
| Auth | JWT (HS256) with rotating refresh tokens |
| Background Jobs | MongoDB-backed durable queue + worker process |

## Repository Structure

```
vedax-ai/
├── apps/
│   ├── api/                 # FastAPI backend
│   │   ├── app/
│   │   │   ├── api/         # REST endpoints (auth, documents, datasets, media, chat, etc.)
│   │   │   ├── agents/      # LangGraph orchestration (graph, state, events, orchestrator)
│   │   │   ├── rag/         # Retrieval (vector + lexical + RRF), embeddings, reranking
│   │   │   ├── vision/      # Vision/OCR analysis (Gemma 4)
│   │   │   ├── audio/       # Speech-to-text (Groq Whisper)
│   │   │   ├── data/        # Structured data analysis (typed op plan interpreter)
│   │   │   ├── providers/   # Model router (Ollama, Groq, Cerebras, mock)
│   │   │   ├── ingestion/   # Document parsing (pymupdf4llm), chunking, indexing
│   │   │   ├── services/    # Business logic, job queue
│   │   │   ├── evaluation/  # RAG/agent benchmarks
│   │   │   ├── observability/
│   │   │   ├── integrations/ # Telegram bot
│   │   │   └── worker/      # Background job worker process
│   │   ├── scripts/         # Setup scripts (search indexes, eval seeding)
│   │   ├── tests/
│   │   └── pyproject.toml
│   └── web/                 # Next.js frontend
│       ├── app/             # 10 routes (landing, login, dashboard, workspace, etc.)
│       ├── components/      # Sidebar, AppLayout
│       ├── lib/             # api, store, types, utils
│       └── package.json
├── evaluation/
│   └── datasets/            # Eval cases (direct, multi-hop, table, handwriting, vision, audio)
├── infra/
│   └── docker/              # Dockerfiles for API and worker
└── render.yaml              # Render deployment config
```

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

## Key Features

- **Multi-query retrieval**: Generates alternative search queries when initial results are sparse
- **Hybrid search**: Vector (Atlas vectorSearch) + lexical (Atlas search) fused via RRF, then LLM-reranked
- **Typed data analysis**: No `exec()` — 7 safe operations (filter, group_by, sort, select, compute, compare_periods, detect_anomaly)
- **Vision pipeline**: Region detection, content type classification, structured OCR
- **Evidence verification**: LLM-based evidence sufficiency check with retry loop
- **Streaming**: SSE-based real-time response streaming
- **Job queue**: MongoDB-backed durable queue with worker process

## Deployment

| Component | Target |
|-----------|--------|
| Frontend | Vercel (Next.js) |
| API | Render (Docker) |
| Worker | Render (Docker, separate service) |
| Database | MongoDB Atlas (M0+) |
| Media | Cloudinary |
| Observability | Langfuse Cloud |

## Environment Variables

See `apps/api/.env.example`. Required for production:
- `MONGODB_URI` — MongoDB Atlas connection string
- `SECRET_KEY` — JWT signing secret
- `OLLAMA_API_KEY` — Ollama Cloud credentials
- `GROQ_API_KEY` — Groq API key
- `GEMINI_API_KEY` — Google AI (Gemini embeddings)
- `CLOUDINARY_*` — Cloudinary credentials
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_WEBHOOK_SECRET` — Telegram bot

## License

MIT — see [LICENSE](LICENSE)
