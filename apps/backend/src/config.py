"""Application configuration using Pydantic Settings.

Environment Variable Strategy:
- Required fields have development defaults for local/CI convenience
- Production values come from Vault (see secrets.ctmpl)
- Optional fields have sensible defaults, rarely need override
"""

from functools import cached_property

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_comma_list(value: str | list[str] | None, default: list[str]) -> list[str]:
    """Parse comma-separated string into list."""
    if value is None:
        return default
    if isinstance(value, list):
        return value
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Required (from secrets.ctmpl):
        database_url, s3_endpoint, s3_access_key, s3_secret_key, s3_bucket

    Optional (with defaults):
        All other fields
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ================================================================
    # REQUIRED - must be provided by environment
    # Development defaults provided for local convenience
    # Production values from Vault (secrets.ctmpl)
    # ================================================================

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report"

    # Redis (optional for local, required for staging/prod)
    redis_url: str | None = None

    # S3 / MinIO storage
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = Field(default="minio", validation_alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="minio_local_secret", validation_alias="S3_SECRET_KEY")
    s3_bucket: str = "statements"

    # ================================================================
    # OPTIONAL - have sensible defaults, rarely need override
    # ================================================================

    # AI API (empty = AI features disabled)
    openrouter_api_key: str = ""

    # App settings
    debug: bool = False
    base_currency: str = "SGD"

    # CORS origins - stored as string, parsed via property
    # Env format: CORS_ORIGINS="http://localhost:3000,http://localhost:3001"
    cors_origins_str: str | None = Field(default=None, validation_alias="CORS_ORIGINS")

    # CORS origin regex - for dynamic subdomains (PR deployments)
    cors_origin_regex: str = r"https://.*\.zitian\.party"

    # OpenRouter settings
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    primary_model: str = "google/gemini-2.0-flash-exp:free"
    fallback_models_str: str | None = Field(default=None, validation_alias="FALLBACK_MODELS")
    openrouter_daily_limit_usd: int | None = 2

    # S3 optional settings
    s3_region: str = "us-east-1"
    s3_presign_expiry_seconds: int = 900

    @cached_property
    def cors_origins(self) -> list[str]:
        """Parse CORS origins from env string or use defaults."""
        return parse_comma_list(
            self.cors_origins_str,
            [
                "http://localhost:3000",
                "http://localhost:3001",
                "http://127.0.0.1:3000",
                "https://report.zitian.party",
            ],
        )

    @cached_property
    def fallback_models(self) -> list[str]:
        """Parse fallback models from env string or use defaults."""
        return parse_comma_list(
            self.fallback_models_str,
            [
                "google/gemini-flash-1.5-8b:free",
                "mistralai/pixtral-12b:free",
            ],
        )


settings = Settings()
