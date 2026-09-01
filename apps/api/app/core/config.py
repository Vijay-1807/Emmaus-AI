from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "VedaX AI"
    environment: str = "development"
    api_prefix: str = "/api"

    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "vedax"

    cors_origins: str = "http://localhost:3000"

    ollama_api_key: str = ""
    ollama_base_url: str = "https://ollama.com/v1"
    ollama_chat_model: str = "gpt-oss:120b"
    ollama_vision_model: str = "gemma4:31b"

    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_chat_model: str = "llama-3.3-70b-versatile"
    groq_fast_model: str = "llama-3.1-8b-instant"
    groq_stt_model: str = "whisper-large-v3-turbo"

    cerebras_api_key: str = ""
    cerebras_base_url: str = "https://api.cerebras.ai/v1"
    cerebras_chat_model: str = "llama-3.3-70b"

    embedding_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_embedding_dimensions: int = 3072
    embedding_base_url: str = "https://ollama.com/v1"
    embedding_api_key: str = ""
    embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = 768
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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def has_ollama(self) -> bool:
        return bool(self.ollama_api_key)

    @property
    def has_groq(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def has_cerebras(self) -> bool:
        return bool(self.cerebras_api_key)

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
