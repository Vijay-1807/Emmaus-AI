# Architecture

VedaX AI is a multimodal agentic knowledge and analysis platform that combines RAG, data analysis, vision/OCR, and agentic reasoning.

## System Overview

```
Next.js Frontend (Vercel)
        │
        │  SSE / REST
        ▼
FastAPI Backend (Render)
        │
        ├── LangGraph Orchestrator (8-node conditional pipeline)
        │       │
        │       ├── transcribe  (audio → text via Groq Whisper)
        │       ├── classify    (route to capabilities via LLM)
        │       ├── rag         (multi-query retrieval + rerank)
        │       ├── data        (typed pandas operations)
        │       ├── vision      (Gemma 4 vision analysis)
        │       ├── fuse        (combine all evidence)
        │       ├── verify      (LLM evidence sufficiency check)
        │       └── generate    (streamed final answer)
        │
        ├── Model Router (Ollama → Groq → Cerebras → Mock fallback)
        ├── Embedding Service (Gemini 001 → Ollama → Local → Mock)
        ├── RAG Pipeline (Vector + Lexical + RRF + Rerank)
        ├── Background Worker (MongoDB job queue)
        └── Telegram Bot

MongoDB Atlas (metadata + vector search + lexical search)
Cloudinary (media storage)
Langfuse (observability traces)
```

## Data Flow

1. User asks a question (text, voice, or camera)
2. **Transcribe**: If voice input, transcribe via Groq Whisper
3. **Classify**: LLM determines which capabilities are needed (rag, data, vision, [])
4. **Retrieve/Analyze**: Route to appropriate nodes in parallel
5. **Fuse**: Combine all evidence (document chunks, data results, vision analysis)
6. **Verify**: LLM checks if evidence is sufficient; retry retrieval once if not
7. **Generate**: Stream final answer with citations and charts

## Key Design Decisions

- **Typed data analysis**: No `exec()` — 7 allow-listed operations executed safely
- **Fail-closed embeddings**: Production requires working embedding provider
- **Workspace isolation**: Every query filters by workspace_id
- **Graceful degradation**: MockProvider always available as last fallback
- **Multi-query retrieval**: Auto-generates alternative queries when initial results are sparse
