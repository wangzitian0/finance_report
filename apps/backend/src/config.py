"""Application configuration using Pydantic Settings.

Environment Variable Strategy:
- Required fields have development defaults for local/CI convenience
- Production values come from Vault (see secrets.ctmpl)
- Optional fields have sensible defaults, rarely need override
"""

from functools import cached_property

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_comma_list(value: str | list[str] | None, default: list[str]) -> list[str]:
    """Parse comma-separated string into list."""
    if value is None:
        return default
    if isinstance(value, list):
        return value
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_key_value_pairs(value: str | None) -> dict[str, str]:
    """Parse comma-separated key=value pairs into a dict."""
    if not value:
        return {}
    pairs: dict[str, str] = {}
    for item in value.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, raw_value = item.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if key and raw_value:
            pairs[key] = raw_value
    return pairs


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
    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report"

    # Redis (optional for local, required for staging/prod)
    redis_url: str | None = None

    # S3 / MinIO storage
    s3_endpoint: str = "http://127.0.0.1:9000"
    s3_access_key: str = Field(default="minio", validation_alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="minio_local_secret", validation_alias="S3_SECRET_KEY")
    s3_bucket: str = "statements"

    # S3 / MinIO public access (for external AI services)
    # If not set, falls back to internal S3 settings
    s3_public_endpoint: str | None = Field(default=None, validation_alias="S3_PUBLIC_ENDPOINT")
    s3_public_access_key: str | None = Field(default=None, validation_alias="S3_PUBLIC_ACCESS_KEY")
    s3_public_secret_key: str | None = Field(default=None, validation_alias="S3_PUBLIC_SECRET_KEY")
    s3_public_bucket: str | None = Field(default=None, validation_alias="S3_PUBLIC_BUCKET")

    # ================================================================
    # OPTIONAL - have sensible defaults, rarely need override
    # ================================================================

    # Security
    secret_key: str = Field(default="dev_secret_key_change_in_prod", validation_alias="SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(
        default=60 * 24, validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES"
    )

    # AI API (empty = AI features disabled)
    openrouter_api_key: str = ""

    # App settings
    environment: str = Field(
        default="development", validation_alias=AliasChoices("ENVIRONMENT", "ENV")
    )
    debug: bool = False
    base_currency: str = "SGD"
    # Backend reference to the frontend URL; should match the frontend NEXT_PUBLIC_APP_URL
    # and is used by backend components when they need to link to the frontend app.
    next_public_app_url: str = Field(
        default="http://localhost:3000",
        validation_alias="NEXT_PUBLIC_APP_URL",
    )

    # CORS origins - stored as string, parsed via property
    # Env format: CORS_ORIGINS="http://localhost:3000,http://localhost:3001"
    cors_origins_str: str | None = Field(default=None, validation_alias="CORS_ORIGINS")

    # CORS origin regex - for dynamic subdomains (PR deployments and staging)
    cors_origin_regex: str = r"https://report(-pr-\d+|-staging)?\.zitian\.party"

    # OpenRouter settings
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    primary_model: str = "google/gemini-3-flash-preview"
    fallback_models_str: str | None = Field(default=None, validation_alias="FALLBACK_MODELS")
    openrouter_daily_limit_usd: int | None = 2

    # S3 optional settings
    s3_region: str = "us-east-1"
    s3_presign_expiry_seconds: int = 900

    # Observability (optional)
    otel_exporter_otlp_endpoint: str | None = Field(
        default="https://signoz-staging.zitian.party",
        validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT",
    )
    otel_service_name: str = Field(
        default="finance-report-backend",
        validation_alias="OTEL_SERVICE_NAME",
    )
    otel_resource_attributes: str | None = Field(
        default=None,
        validation_alias="OTEL_RESOURCE_ATTRIBUTES",
    )

    # Feature Flags for 4-Layer Architecture Migration (EPIC-011)
    enable_4_layer_write: bool = Field(
        default=False,
        validation_alias="ENABLE_4_LAYER_WRITE",
    )
    enable_4_layer_read: bool = Field(
        default=False,
        validation_alias="ENABLE_4_LAYER_READ",
    )
    enable_layer_0_write: bool = Field(
        default=True,
        validation_alias="ENABLE_LAYER_0_WRITE",
    )

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
                "qwen/qwen-2.5-vl-7b-instruct:free",
                "nvidia/nemotron-nano-12b-v2-vl:free",
            ],
        )


settings = Settings()
