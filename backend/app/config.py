from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_name: str = "ProductLens AI"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_admin_url: str = "postgresql+psycopg://productlens:productlens@localhost:5432/productlens"
    app_database_url: str = "postgresql+psycopg://productlens:productlens@localhost:5432/productlens"
    analytics_database_url: str = "postgresql+psycopg://productlens:productlens@localhost:5432/productlens"
    frontend_origin: str = "http://localhost:3000"
    session_hmac_secret: SecretStr = SecretStr("development-only-secret-change-me")
    llm_provider: str = "gemini"
    llm_model: str = "gemini-3.7-flash"
    llm_fallback_provider: str = "groq"
    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    groq_model: str = "openai/gpt-oss-20b"
    ai_requests_per_session_hour: int = Field(default=10, ge=1, le=1000)
    ai_requests_global_day: int = Field(default=100, ge=1, le=100_000)
    result_cache_ttl_seconds: int = Field(default=300, ge=0, le=86_400)
    query_timeout_ms: int = Field(default=5000, ge=100, le=60_000)
    max_query_rows: int = Field(default=5000, ge=1, le=50_000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
