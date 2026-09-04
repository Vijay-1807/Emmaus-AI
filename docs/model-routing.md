# Model Routing

## Task Types

| TaskType | Purpose | Primary Provider | Fallback Chain |
|----------|---------|-----------------|----------------|
| REASONING | Final answer generation | Groq (openai/gpt-oss-120b) | Ollama → Mock |
| CLASSIFY | Intent routing | Groq (openai/gpt-oss-20b) | Ollama → Mock |
| REWRITE | Query rewriting | Groq (openai/gpt-oss-20b) | Ollama → Mock |
| RERANK | Relevance scoring | Groq (openai/gpt-oss-20b) | Ollama → Mock |
| VERIFY | Evidence sufficiency | Groq (openai/gpt-oss-20b) | Ollama → Mock |
| VISION | Image analysis | Groq (qwen/qwen3.6-27b) | Ollama (gemma4:31b) → Mock |
| EXTRACTION | Structured output | Groq (openai/gpt-oss-20b) | Ollama → Mock |
| EVALUATION | Answer grading | Groq (openai/gpt-oss-20b) | Ollama → Mock |

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

## Retry Logic

- 3 attempts per provider
- Exponential backoff: 0.8s, 1.6s, 3.2s
- Timeout: provider-specific (default 60s)

## Observability

Every LLM call is recorded to:
1. **Internal**: `model_runs` collection in MongoDB (provider, model, task, tokens, latency)
2. **Langfuse**: Trace span with model, input/output preview, token usage, latency
