# Model Routing

## Task Types

| TaskType | Purpose | Primary Provider | Fallback Chain |
|----------|---------|-----------------|----------------|
| REASONING | Final answer generation | Ollama (gpt-oss:120b) | Groq → Cerebras → Mock |
| CLASSIFY | Intent routing | Groq (llama-3.1-8b-instant) | Ollama → Cerebras → Mock |
| REWRITE | Query rewriting | Groq (llama-3.1-8b-instant) | Ollama → Cerebras → Mock |
| RERANK | Relevance scoring | Groq (llama-3.1-8b-instant) | Ollama → Cerebras → Mock |
| VERIFY | Evidence sufficiency | Groq (llama-3.1-8b-instant) | Ollama → Cerebras → Mock |
| VISION | Image analysis | Ollama (gemma4:31b) | Mock |
| EXTRACTION | Structured output | Groq (llama-3.1-8b-instant) | Ollama → Cerebras → Mock |
| EVALUATION | Answer grading | Groq (llama-3.1-8b-instant) | Ollama → Cerebras → Mock |

## Fallback Behavior

The model router tries providers in chain order. If a provider fails (timeout, rate limit, auth error), it:

1. Logs the error
2. Tries the next provider in the chain
3. MockProvider is always last (never fails, returns structured mock data)

In production, if all real providers fail, the system degrades to mock responses.

## Cost Estimation

| Provider | Model | Input $/MTok | Output $/MTok |
|----------|-------|-------------|---------------|
| Groq | llama-3.3-70b-versatile | $0.59 | $0.79 |
| Groq | llama-3.1-8b-instant | $0.05 | $0.08 |
| Cerebras | llama-3.3-70b | $0.85 | $1.20 |
| Ollama | gpt-oss:120b | $0.50 | $1.50 |

## Retry Logic

- 3 attempts per provider
- Exponential backoff: 0.8s, 1.6s, 3.2s
- Timeout: provider-specific (default 60s)

## Observability

Every LLM call is recorded to:
1. **Internal**: `model_runs` collection in MongoDB (provider, model, task, tokens, latency)
2. **Langfuse**: Trace span with model, input/output preview, token usage, latency
