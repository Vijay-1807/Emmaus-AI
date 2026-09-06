# Model Routing

## Task Types

| TaskType | Purpose | Primary Provider | Fallback Chain |
|----------|---------|-----------------|----------------|
| REASONING | Final answer generation | Groq (openai/gpt-oss-120b) | Ollama → Mock |
| CLASSIFY | Intent routing | Ollama (gpt-oss:120b) | Groq (openai/gpt-oss-20b) → Mock |
| REWRITE | Query rewriting | Ollama (gpt-oss:120b) | Groq (openai/gpt-oss-20b) → Mock |
| RERANK | Relevance scoring | Ollama (gpt-oss:120b) | Groq (openai/gpt-oss-20b) → Mock |
| VERIFY | Evidence sufficiency | Ollama (gpt-oss:120b) | Groq (openai/gpt-oss-20b) → Mock |
| VISION | Image analysis | Ollama (gemma4:31b) | Groq (qwen/qwen3.6-27b) → Mock |
| EXTRACTION | Structured output | Ollama (gpt-oss:120b) | Groq (openai/gpt-oss-20b) → Mock |
| EVALUATION | Answer grading | Ollama (gpt-oss:120b) | Groq (openai/gpt-oss-20b) → Mock |

## Fallback Behavior

The model router tries providers in chain order. If a provider fails (timeout, rate limit, auth error), it:

1. Logs the error
2. Tries the next provider in the chain
3. MockProvider is always last (never fails, returns structured mock data)

In production, if all real providers fail, the system degrades to mock responses.

## Cost Estimation

| Provider | Model | Input $/MTok | Output $/MTok |
|----------|-------|-------------|---------------|
| Groq | openai/gpt-oss-120b | $0.15 | $0.60 |
| Groq | openai/gpt-oss-20b | $0.075 | $0.30 |
| Groq | qwen/qwen3.6-27b (vision) | $0.60 | $3.00 |
| Ollama | gpt-oss:120b | $0.00 | $0.00 |

## Image Generation (outside the router)

Text-to-image runs on Cloudflare Workers AI (`@cf/black-forest-labs/flux-1-schnell`), not through the Groq/Ollama fallback chain. Free tier: 10,000 neurons/day, no credit card. Endpoints: `POST /api/image/generate`, `GET /api/image/status`.

## Retry Logic

- 3 attempts per provider (then falls through to next provider in chain)
- Exponential backoff: 0.8s, 1.6s, 3.2s + Retry-After header honoring
- Per-provider concurrency semaphore (default 3, `PROVIDER_MAX_CONCURRENCY`)
- Timeout: provider-specific (default 60s)

## Observability

Every LLM call is recorded to:
1. **Internal**: `model_runs` collection in MongoDB (provider, model, task, tokens, latency)
2. **Langfuse**: Trace span with model, input/output preview, token usage, latency
