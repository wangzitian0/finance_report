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

    # Connection Pool (optional tuning)
    db_pool_size: int = Field(default=5, ge=1, validation_alias="DB_POOL_SIZE")
    db_pool_max_overflow: int = Field(default=10, ge=0, validation_alias="DB_POOL_MAX_OVERFLOW")

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
    access_token_expire_minutes: int = Field(default=60 * 24, validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES")

    # AI provider (empty key = AI features disabled)
    ai_provider: str = Field(default="zai", validation_alias="AI_PROVIDER")
    ai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("ZAI_API_KEY", "GLM_API_KEY", "AI_API_KEY", "OPENROUTER_API_KEY"),
    )

    # App settings
    environment: str = Field(default="development", validation_alias=AliasChoices("ENVIRONMENT", "ENV"))
    debug: bool = False
    base_currency: str = "SGD"
    redis_url: str | None = Field(default=None, validation_alias="REDIS_URL")
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

    # AI model provider settings. Defaults target Z.AI/GLM, but these remain
    # provider-neutral so the base model can be swapped through env vars.
    ai_base_url: str = Field(
        default="https://api.z.ai/api/paas/v4",
        validation_alias=AliasChoices("AI_BASE_URL", "ZAI_BASE_URL", "OPENROUTER_BASE_URL"),
    )
    ai_chat_completions_path: str = Field(
        default="/chat/completions",
        validation_alias="AI_CHAT_COMPLETIONS_PATH",
    )
    ai_layout_parsing_path: str = Field(
        default="/layout_parsing",
        validation_alias="AI_LAYOUT_PARSING_PATH",
    )
    ai_model_catalog_source: str = Field(
        default="configured",
        validation_alias="AI_MODEL_CATALOG_SOURCE",
    )
    primary_model: str = Field(default="glm-5.1", validation_alias="PRIMARY_MODEL")
    vision_model: str = Field(default="glm-5v-turbo", validation_alias="VISION_MODEL")
    ocr_model: str = Field(default="glm-ocr", validation_alias="OCR_MODEL")
    fallback_models_str: str | None = Field(default=None, validation_alias="FALLBACK_MODELS")
    ai_daily_limit_usd: int | None = Field(default=2, validation_alias="AI_DAILY_LIMIT_USD")

    # S3 optional settings
    s3_region: str = "us-east-1"
    s3_presign_expiry_seconds: int = 300

    # Observability (optional)
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None,
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
    # Feature Flags for AI-Driven Pipeline (EPIC-018)
    enable_ai_reconciliation: bool = Field(
        default=False,
        validation_alias="ENABLE_AI_RECONCILIATION",
    )
    enable_ai_classification: bool = Field(
        default=False,
        description="Enable AI-assisted transaction classification suggestions.",
        validation_alias="ENABLE_AI_CLASSIFICATION",
    )

    # Storage Sweep
    enable_storage_sweep: bool = Field(
        default=True,
        description="Enable periodic background sweep for orphaned S3 objects. Disable in test environments.",
        validation_alias="ENABLE_STORAGE_SWEEP",
    )

    # Deployment metadata
    git_commit_sha: str = Field(
        default="unknown",
        validation_alias="GIT_COMMIT_SHA",
    )

    # Rate Limiting (global API protection)
    api_rate_limit_requests: int = Field(default=300, ge=1, validation_alias="API_RATE_LIMIT_REQUESTS")
    api_rate_limit_window: int = Field(default=60, ge=1, validation_alias="API_RATE_LIMIT_WINDOW")
    register_rate_limit_requests: int = Field(default=10, ge=1, validation_alias="REGISTER_RATE_LIMIT_REQUESTS")
    register_rate_limit_window: int = Field(default=600, ge=1, validation_alias="REGISTER_RATE_LIMIT_WINDOW")

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
                "glm-5-turbo",
                "glm-5",
            ],
        )

    @property
    def openrouter_api_key(self) -> str:
        """Backward-compatible alias for legacy internal call sites/tests."""
        return self.ai_api_key

    @openrouter_api_key.setter
    def openrouter_api_key(self, value: str) -> None:
        self.ai_api_key = value

    @property
    def openrouter_base_url(self) -> str:
        """Backward-compatible alias for legacy internal call sites/tests."""
        return self.ai_base_url

    @openrouter_base_url.setter
    def openrouter_base_url(self, value: str) -> None:
        self.ai_base_url = value

    @property
    def openrouter_daily_limit_usd(self) -> int | None:
        """Backward-compatible alias for legacy internal call sites/tests."""
        return self.ai_daily_limit_usd

    @openrouter_daily_limit_usd.setter
    def openrouter_daily_limit_usd(self, value: int | None) -> None:
        self.ai_daily_limit_usd = value


settings = Settings()
