from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class TenantSourceConfig(BaseModel):
    kind: Literal["postgres"] = "postgres"
    source_id: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    url_env: str = Field(min_length=2, max_length=128, pattern=r"^[A-Z][A-Z0-9_]*$")


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
    access_token_secret: SecretStr | None = None
    oidc_issuer_url: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_workspace_claim: str = "workspace_id"
    oidc_groups_claim: str = "groups"
    oidc_role_groups: dict[str, list[str]] = Field(default_factory=dict)
    oidc_jwks_cache_ttl_seconds: int = Field(default=300, ge=30, le=86_400)
    oidc_jwks_timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0)
    tenant_source_config: dict[str, TenantSourceConfig] = Field(default_factory=dict)
    # This optional local-development escape hatch keeps the source registry
    # server-side while allowing a .env file to provide URL values. Vercel
    # deployments should use url_env and separate secret environment values.
    tenant_source_urls: dict[str, SecretStr] = Field(default_factory=dict)
    sse_max_duration_seconds: int = Field(default=20, ge=1, le=55)
    sse_poll_interval_seconds: int = Field(default=5, ge=1, le=15)
    multi_agent_enabled: bool = True
    multi_agent_timeout_ms: int = Field(default=10_000, ge=1_000, le=30_000)
    ai_requests_per_session_hour: int = Field(default=10, ge=1, le=1000)
    ai_requests_global_day: int = Field(default=100, ge=1, le=100_000)
    result_cache_ttl_seconds: int = Field(default=300, ge=0, le=86_400)
    query_timeout_ms: int = Field(default=5000, ge=100, le=60_000)
    max_query_rows: int = Field(default=5000, ge=1, le=50_000)
    proactive_report_budget_ms: int = Field(default=45_000, ge=5_000, le=60_000)
    report_provider_timeout_ms: int = Field(default=2_500, ge=0, le=10_000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
