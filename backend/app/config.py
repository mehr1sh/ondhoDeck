"""Runtime configuration from environment variables (see backend/.env.example)."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "preview", "production"] = "development"
    log_level: str = "INFO"

    # Database (Supabase Postgres in preview/production)
    database_url: str = "postgresql+psycopg://slipslopes:slipslopes@localhost:54329/slipslopes"

    # Supabase Auth: tokens are verified server-side. Asymmetric keys are fetched from the JWKS
    # endpoint; the legacy HS256 shared secret is supported for older projects and local GoTrue.
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    supabase_jwt_audience: str = "authenticated"
    supabase_service_role_key: str = ""  # server-only: never expose to the browser

    # Object storage
    storage_backend: Literal["supabase", "local"] = "local"
    storage_bucket: str = "documents"
    local_storage_dir: str = ".storage"  # development/test only
    signed_url_ttl_seconds: int = Field(120, ge=10, le=3600)

    # Queue
    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = False  # tests only

    # Document limits
    max_upload_mb: int = Field(50, ge=1, le=200)
    max_pdf_pages: int = Field(1500, ge=1)
    ocr_enabled: bool = True
    ocr_max_pages: int = Field(40, ge=0)
    processing_time_limit_s: int = Field(900, ge=30)
    max_job_attempts: int = Field(3, ge=1, le=10)

    # Server-level LLM extraction (optional). Users can also bring their own key (BYOK, stored encrypted).
    # With no BYOK key and LLM_PROVIDER=none, deterministic rule-based extraction is used.
    llm_provider: Literal["anthropic", "openai", "none"] = "none"
    anthropic_api_key: str = ""
    anthropic_workspace_id: str = ""  # only for Anthropic keys not scoped to a workspace
    llm_model: str = "claude-opus-5-5"   # model for the server Anthropic provider
    openai_api_key: str = ""
    openai_model: str = ""               # required when LLM_PROVIDER=openai (no default is assumed)
    llm_effort: Literal["low", "medium", "high"] = "medium"
    llm_max_excerpts: int = Field(8, ge=1, le=30)
    llm_timeout_s: int = Field(180, ge=10)

    # BYOK credential encryption: comma-separated Fernet keys (first encrypts; all decrypt, for rotation).
    # When empty, storing user API keys is disabled - keys are never stored unencrypted.
    credentials_encryption_keys: str = ""
    rate_limit_provider_tests_per_10min: int = 10

    # HTTP
    cors_origins: str = "http://localhost:3000"
    rate_limit_extraction_per_hour: int = 30
    rate_limit_compute_per_minute: int = 20
    rate_limit_chat_per_minute: int = 10

    # Retention: deleted documents' stored objects and page text are purged immediately;
    # the document row is kept (status=deleted, no content) for audit.
    reporting_currency_default: str = "USD"

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard(cls, v: str) -> str:
        if "*" in v:
            raise ValueError("CORS origins must be explicit; '*' is not allowed")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @property
    def jwks_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json" if self.supabase_url else ""

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1" if self.supabase_url else ""

    @field_validator("llm_model")
    @classmethod
    def _default_model_when_blank(cls, v: str) -> str:
        return v.strip() or "claude-opus-5-5"

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.llm_provider == "openai":
            return bool(self.openai_api_key and self.openai_model)
        return False

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.environment in ("preview", "production"):
            if self.storage_backend != "supabase":
                raise ValueError("preview/production must use Supabase Storage (STORAGE_BACKEND=supabase)")
            if not self.supabase_url or not self.supabase_service_role_key:
                raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required outside development")
            if self.celery_task_always_eager:
                raise ValueError("CELERY_TASK_ALWAYS_EAGER must be false outside tests")
        if not self.supabase_url and not self.supabase_jwt_secret:
            raise ValueError("Configure SUPABASE_URL (JWKS) and/or SUPABASE_JWT_SECRET for token verification")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
