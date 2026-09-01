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
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind, Recharts |
| Backend | FastAPI, Python 3.11+, Pydantic, Motor → PyMongo Async |
| Orchestration | LangGraph, LangChain components |
| Database | MongoDB Atlas (Vector Search + Atlas Search) |
| Media | Cloudinary |
| Models | Ollama Cloud (gpt-oss:120b, gemma4:31b), Groq (llama-3.1-8b-instant, llama-3.3-70b-versatile, whisper-large-v3-turbo), Cerebras (optional), Gemini Embedding 2 |
| Observability | Langfuse |
| CI/CD | GitHub Actions, Docker |
| Auth | JWT (HS256) with rotating refresh tokens |

## Repository Structure

```
vedax-ai/
├── apps/
│   ├── api/                 # FastAPI backend (this repo)
│   │   ├── app/
│   │   │   ├── api/         # REST endpoints
│   │   │   ├── agents/      # LangGraph orchestration
│   │   │   ├── rag/         # Retrieval, embeddings, reranking
│   │   │   ├── vision/      # Vision/OCR analysis
│   │   │   ├── audio/       # Speech-to-text
│   │   │   ├── data/        # Structured data analysis
│   │   │   ├── providers/   # Model provider abstractions
│   │   │   ├── ingestion/   # Document parsing, chunking, indexing
│   │   │   ├── services/    # Business logic
│   │   │   ├── evaluation/  # RAG/agent benchmarks
│   │   │   └── observability/
│   │   ├── tests/
│   │   └── pyproject.toml
│   └── web/                 # Next.js frontend (to be created)
├── packages/
│   ├── shared-types/
│   └── prompts/
├── evaluation/
│   ├── datasets/
│   ├── runners/
│   └── reports/
├── infra/
│   └── docker/
├── docs/
└── README.md
```

## Quick Start (Backend)

```bash
cd apps/api
cp .env.example .env
# Edit .env with your keys
uv sync
uv run python -m app.main
```

## Environment Variables

See `apps/api/.env.example` for all options. Required for production:
- `MONGODB_URI` — MongoDB Atlas connection string
- `SECRET_KEY` — JWT signing secret (long random string)
- `OLLAMA_API_KEY`, `OLLAMA_BASE_URL` — Ollama Cloud credentials
- `GROQ_API_KEY` — Groq API key
- `GEMINI_API_KEY` — Google AI API key (for Gemini Embedding 2)
- `CLOUDINARY_*` — Cloudinary credentials
- `LANGFUSE_*` — Langfuse credentials (optional)

## Deployment

| Component | Target |
|-----------|--------|
| Frontend | Vercel (Next.js) |
| API + Worker | Render (Docker) |
| Database | MongoDB Atlas (M0+) |
| Media | Cloudinary |
| Observability | Langfuse Cloud |

## License

MIT — see [LICENSE](LICENSE)