from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Emmaus AI"
    environment: str = "development"
    api_prefix: str = "/api"

    secret_key: str = "dev-secret-change-me"

    def model_post_init(self, __context: Any) -> None:
        if self.environment == "production" and self.secret_key == "dev-secret-change-me":
            raise ValueError("SECRET_KEY must be set to a secure value in production")
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "vedax"

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Cerebras is retained as disabled legacy configuration.
    cerebras_api_key: str = ""
    cerebras_base_url: str = "https://api.cerebras.ai/v1"
    cerebras_chat_model: str = "gpt-oss-120b"
    cerebras_vision_model: str = "gemma-4-31b"

    # Groq (SECONDARY - fast + STT)
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_chat_model: str = "openai/gpt-oss-120b"
    # llama-3.1-8b-instant was deprecated by Groq on 2026-08-16;
    # official replacement is openai/gpt-oss-20b.
    groq_fast_model: str = "openai/gpt-oss-20b"
    groq_stt_model: str = "whisper-large-v3-turbo"
    # llama-4-scout was deprecated by Groq on 2026-07-17;
    # qwen3.6-27b is the live multimodal model (vision + JSON mode + tools).
    groq_vision_model: str = "qwen/qwen3.6-27b"

    # Ollama Cloud (TERTIARY fallback)
    ollama_api_key: str = ""
    ollama_base_url: str = "https://ollama.com/v1"
    ollama_chat_model: str = "gpt-oss:120b"
    ollama_vision_model: str = "gemma4:31b"
    ollama_fallback_models: str = "gpt-oss:20b,nemotron-3-nano:30b,nemotron-3-super"

    # Sarvam STT (PRIMARY - Indian languages)
    sarvam_api_key: str = ""
    sarvam_base_url: str = "https://api.sarvam.ai/v1"
    sarvam_stt_model: str = "saaras:v4"

    # Deepgram STT (SECONDARY fallback)
    deepgram_api_key: str = ""
    deepgram_base_url: str = "https://api.deepgram.com/v1"
    deepgram_stt_model: str = "nova-3"

    # Embeddings
    embedding_provider: str = "jina"
    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_embedding_dimensions: int = 3072
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "jina-embeddings-v5-omni-small"
    embedding_dimensions: int = 1024
    local_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    media_storage: str = "auto"
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    vector_search_top_k: int = 30
    lexical_search_top_k: int = 30
    final_top_k: int = 6
    rrf_k: int = 60

    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""

    max_upload_mb: int = 25

    # Max concurrent non-streaming LLM calls per provider. Caps burst
    # traffic so parallel investigations don't stampede free-tier TPM limits.
    provider_max_concurrency: int = 3

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def has_cerebras(self) -> bool:
        return bool(self.cerebras_api_key)

    @property
    def has_groq(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def has_ollama(self) -> bool:
        return bool(self.ollama_api_key)

    @property
    def has_jina(self) -> bool:
        return bool(self.embedding_api_key)

    @property
    def has_sarvam(self) -> bool:
        return bool(self.sarvam_api_key)

    @property
    def has_deepgram(self) -> bool:
        return bool(self.deepgram_api_key)

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def has_cloudinary(self) -> bool:
        return bool(
            self.cloudinary_cloud_name and self.cloudinary_api_key and self.cloudinary_api_secret
        )

    @property
    def has_langfuse(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
