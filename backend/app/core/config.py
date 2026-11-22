"""Application configuration validated via pydantic-settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    app_version: str = "0.1.0"

    # Database URLs (app_user enforces RLS; migration URL uses table owner)
    database_url: str = "postgresql+asyncpg://app_user:app_dev_password@localhost:5432/chatbot"
    database_migration_url: str = (
        "postgresql+asyncpg://postgres:postgres_dev_password@localhost:5432/chatbot"
    )
    test_database_url: str = (
        "postgresql+asyncpg://app_user:app_dev_password@localhost:5432/chatbot_test"
    )
    test_database_migration_url: str = (
        "postgresql+asyncpg://postgres:postgres_dev_password@localhost:5432/chatbot_test"
    )

    # Redis / ARQ
    redis_url: str = "redis://localhost:6379/0"

    # S3 / MinIO storage
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin_dev_password"
    s3_bucket: str = "knowledge-base"

    # Embeddings (locked at 1024 dimensions across providers)
    embedding_provider: Literal["bge_m3", "openai", "mock"] = "bge_m3"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimensions: int = Field(default=1024, ge=1)
    openai_api_key: str = ""

    # LLM (Anthropic Claude)
    anthropic_api_key: str = ""
    llm_default_model: str = "claude-haiku-4-5-20251001"
    llm_escalation_model: str = "claude-sonnet-4-5-20250929"
    llm_escalation_enabled: bool = False

    # Security & Auth
    fernet_key: str = ""
    supabase_url: str = ""
    supabase_jwks_url: str = ""
    dev_jwt_secret: str = "dev-only-change-me-in-production"

    # Payments (Omise)
    omise_public_key: str = ""
    omise_secret_key: str = ""
    omise_webhook_secret: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
