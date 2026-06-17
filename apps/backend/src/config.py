"""Application configuration using Pydantic Settings.

Environment Variable Strategy:
- Required fields have development defaults for local/CI convenience
- Production values come from Vault (see secrets.ctmpl)
- Optional fields have sensible defaults, rarely need override
"""

from functools import cached_property

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Environments that are real deployments (infra2 issues the telemetry contract
# here). Local/CI/preview are exempt from the deployed-env fast-fail below.
# Single source of truth — boot.py imports this (config is the lower-level module).
PROTECTED_ENVIRONMENTS = frozenset({"staging", "production"})


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
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report",
        description=("Async SQLAlchemy database URL. Use postgresql+asyncpg:// for async FastAPI compatibility."),
        json_schema_extra={
            "group": "Database",
            "vault": True,
            "example": "postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report",
        },
    )

    # Connection Pool (optional tuning)
    db_pool_size: int = Field(
        default=5,
        ge=1,
        validation_alias="DB_POOL_SIZE",
        description="DB connection pool size (optional tuning for production).",
        json_schema_extra={"group": "Database"},
    )
    db_pool_max_overflow: int = Field(
        default=10,
        ge=0,
        validation_alias="DB_POOL_MAX_OVERFLOW",
        description="DB connection pool max overflow (optional tuning for production).",
        json_schema_extra={"group": "Database"},
    )

    # S3 / MinIO storage
    s3_endpoint: str = Field(
        default="http://127.0.0.1:9000",
        description="S3 / MinIO endpoint used for storing uploaded statement files.",
        json_schema_extra={
            "group": "S3 / MinIO Storage",
            "vault": True,
            "example": "http://localhost:9000",
        },
    )
    s3_access_key: str = Field(
        default="minio",
        validation_alias="S3_ACCESS_KEY",
        description="S3 / MinIO access key.",
        json_schema_extra={"group": "S3 / MinIO Storage", "vault": True},
    )
    s3_secret_key: str = Field(
        default="minio_local_secret",
        validation_alias="S3_SECRET_KEY",
        description="S3 / MinIO secret key.",
        json_schema_extra={
            "group": "S3 / MinIO Storage",
            "vault": True,
            "example": "<YOUR_S3_SECRET_KEY>",
        },
    )
    s3_bucket: str = Field(
        default="statements",
        description="S3 / MinIO bucket name for uploaded statements.",
        json_schema_extra={"group": "S3 / MinIO Storage", "vault": True},
    )

    # S3 / MinIO public access (for external AI services)
    # If not set, falls back to internal S3 settings
    s3_public_endpoint: str | None = Field(
        default=None,
        validation_alias="S3_PUBLIC_ENDPOINT",
        description=(
            "Publicly reachable S3 endpoint for AI services. REQUIRED in production "
            "if S3_ENDPOINT is internal (e.g. http://minio:9000). Some AI providers "
            "need publicly accessible URLs to download statement PDFs for parsing. "
            "If not set, the system sends file_content (Base64) when available and "
            "only falls back to the S3 file_url when no content is provided."
        ),
        json_schema_extra={
            "group": "S3 / MinIO Storage",
            "vault": True,
            "example": "https://your-public-s3-endpoint.example.com",
        },
    )
    s3_public_access_key: str | None = Field(
        default=None,
        validation_alias="S3_PUBLIC_ACCESS_KEY",
        description="Public S3 access key (falls back to internal S3 settings when unset).",
        json_schema_extra={"group": "S3 / MinIO Storage", "vault": True},
    )
    s3_public_secret_key: str | None = Field(
        default=None,
        validation_alias="S3_PUBLIC_SECRET_KEY",
        description="Public S3 secret key (falls back to internal S3 settings when unset).",
        json_schema_extra={"group": "S3 / MinIO Storage", "vault": True},
    )
    s3_public_bucket: str | None = Field(
        default=None,
        validation_alias="S3_PUBLIC_BUCKET",
        description="Public S3 bucket (falls back to internal S3 settings when unset).",
        json_schema_extra={"group": "S3 / MinIO Storage", "vault": True},
    )

    # ================================================================
    # OPTIONAL - have sensible defaults, rarely need override
    # ================================================================

    # Security
    secret_key: str = Field(
        default="dev_secret_key_change_in_prod",
        validation_alias="SECRET_KEY",
        description=("Application secret key. CRITICAL: must be set to a secure random value in production via Vault."),
        json_schema_extra={
            "group": "Security",
            "vault": True,
            "example": "generate_a_secure_token_for_production_here",
        },
    )
    jwt_algorithm: str = Field(
        default="HS256",
        validation_alias="JWT_ALGORITHM",
        description="JWT signing algorithm.",
        json_schema_extra={"group": "Security"},
    )
    access_token_expire_minutes: int = Field(
        default=60 * 24,
        validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES",
        description="Access token lifetime in minutes.",
        json_schema_extra={"group": "Security"},
    )

    # AI provider (empty key = AI features disabled)
    ai_provider: str = Field(
        default="zai",
        validation_alias="AI_PROVIDER",
        description=("AI provider id. Required for document extraction and the AI advisor (Z.AI/GLM defaults)."),
        json_schema_extra={"group": "AI Provider", "vault": True},
    )
    ai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("ZAI_API_KEY", "GLM_API_KEY", "AI_API_KEY", "OPENROUTER_API_KEY"),
        description=(
            "AI provider API key (empty key = AI features disabled). ZAI_API_KEY is "
            "preferred for the default Z.AI provider; AI_API_KEY is a provider-neutral "
            "alias."
        ),
        json_schema_extra={
            "group": "AI Provider",
            "vault": True,
            "extra_keys": ["AI_API_KEY"],
        },
    )

    # App settings
    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("ENVIRONMENT", "ENV"),
        description="Logical environment name (used to differentiate environments).",
        json_schema_extra={
            "group": "App Settings",
            "vault": True,
            "extra_keys": ["ENV"],
        },
    )
    debug: bool = Field(
        default=False,
        description="Enable debug mode.",
        json_schema_extra={"group": "App Settings", "example": "true"},
    )
    base_currency: str = Field(
        default="SGD",
        description="Base reporting currency (ISO 4217).",
        json_schema_extra={"group": "App Settings"},
    )
    market_data_lazy_fetch_enabled: bool = Field(
        default=True,
        validation_alias="MARKET_DATA_LAZY_FETCH_ENABLED",
        description=("Report-side FX lazy resolution. Set to false to prevent outbound Yahoo Finance calls."),
        json_schema_extra={"group": "App Settings"},
    )
    market_data_fx_bridge_currency: str = Field(
        default="USD",
        validation_alias="MARKET_DATA_FX_BRIDGE_CURRENCY",
        description="Bridge currency used for FX cross-rate resolution.",
        json_schema_extra={"group": "App Settings"},
    )
    market_data_yahoo_timeout_seconds: int = Field(
        default=5,
        ge=1,
        le=30,
        validation_alias="MARKET_DATA_YAHOO_TIMEOUT_SECONDS",
        description="Timeout (seconds) for outbound Yahoo Finance market-data calls.",
        json_schema_extra={"group": "App Settings"},
    )
    redis_url: str | None = Field(
        default=None,
        validation_alias="REDIS_URL",
        description="Optional Redis URL for staging/production background coordination.",
        json_schema_extra={"group": "App Settings"},
    )
    # Backend reference to the frontend URL; should match the frontend NEXT_PUBLIC_APP_URL
    # and is used by backend components when they need to link to the frontend app.
    next_public_app_url: str = Field(
        default="http://localhost:3000",
        validation_alias="NEXT_PUBLIC_APP_URL",
        description=(
            "Backend reference to the frontend URL; should match the frontend "
            "NEXT_PUBLIC_APP_URL and is used by backend components when they link "
            "back to the frontend app."
        ),
        json_schema_extra={"group": "App Settings", "vault": True},
    )

    # CORS origins - stored as string, parsed via property
    # Env format: CORS_ORIGINS="http://localhost:3000,http://localhost:3001"
    cors_origins_str: str | None = Field(
        default=None,
        validation_alias="CORS_ORIGINS",
        description=("Comma-separated CORS origins, e.g. http://localhost:3000,http://localhost:3001."),
        json_schema_extra={
            "group": "Security",
            "vault": True,
            "example": "http://localhost:3000,http://localhost:3001",
        },
    )

    # CORS origin regex - for dynamic subdomains (PR deployments and staging)
    cors_origin_regex: str = Field(
        default=r"https://report(-pr-\d+|-staging)?\.zitian\.party",
        description="CORS origin regex for dynamic subdomains (PR deployments and staging).",
        json_schema_extra={
            "group": "Security",
            "example": r'r"https://report(-pr-\d+|-staging)?\.zitian\.party"',
        },
    )

    # AI model provider settings. Defaults target Z.AI/GLM, but these remain
    # provider-neutral so the base model can be swapped through env vars.
    ai_base_url: str = Field(
        default="https://api.z.ai/api/coding/paas/v4",
        validation_alias=AliasChoices("AI_BASE_URL", "ZAI_BASE_URL", "OPENROUTER_BASE_URL"),
        description="AI provider base URL (provider-neutral; default targets Z.AI/GLM).",
        json_schema_extra={"group": "AI Provider"},
    )
    ai_chat_completions_path: str = Field(
        default="/chat/completions",
        validation_alias="AI_CHAT_COMPLETIONS_PATH",
        description="Chat completions path appended to the AI base URL.",
        json_schema_extra={"group": "AI Provider"},
    )
    ai_layout_parsing_path: str = Field(
        default="/layout_parsing",
        validation_alias="AI_LAYOUT_PARSING_PATH",
        description="Layout-parsing path appended to the AI base URL.",
        json_schema_extra={"group": "AI Provider"},
    )
    primary_model: str = Field(
        default="glm-5.1",
        validation_alias="PRIMARY_MODEL",
        description="Primary AI model id.",
        json_schema_extra={"group": "AI Provider"},
    )
    vision_model: str = Field(
        default="glm-4.6v",
        validation_alias="VISION_MODEL",
        description="Vision AI model id.",
        json_schema_extra={"group": "AI Provider"},
    )
    ocr_model: str = Field(
        default="glm-4.6v",
        validation_alias="OCR_MODEL",
        description="OCR AI model id.",
        json_schema_extra={"group": "AI Provider"},
    )
    fallback_models_str: str | None = Field(
        default=None,
        validation_alias="FALLBACK_MODELS",
        description="Comma-separated fallback AI model ids.",
        json_schema_extra={"group": "AI Provider", "example": "glm-5-turbo,glm-5"},
    )
    vision_fallback_models_str: str | None = Field(
        default=None,
        validation_alias="VISION_FALLBACK_MODELS",
        description=(
            "Comma-separated fallback AI model ids for the vision/OCR path. These "
            "must be vision-capable because the vision request carries image "
            "content; the text-only FALLBACK_MODELS are not reused here (#1034)."
        ),
        json_schema_extra={"group": "AI Provider", "example": "glm-4.5v"},
    )
    # EPIC-019: when set, upload→report parsing is submitted as a durable Prefect
    # flow run instead of an in-process asyncio task. Unset (CI/local/preview) →
    # in-process fallback, no Prefect dependency. See services/statement_pipeline.py.
    prefect_api_url: str | None = Field(
        default=None,
        validation_alias="PREFECT_API_URL",
        description=(
            "EPIC-019: set to the Prefect API URL to run upload->report parsing as "
            "durable Prefect flow runs (staging/prod and per-PR ephemeral Prefect). "
            "Leave unset for CI/local/preview -> in-process asyncio fallback "
            "(no Prefect needed)."
        ),
        json_schema_extra={"group": "AI Provider"},
    )
    ai_json_timeout_seconds: float = Field(
        default=360.0,
        validation_alias="AI_JSON_TIMEOUT_SECONDS",
        description="Timeout (seconds) for AI JSON completion calls.",
        json_schema_extra={"group": "AI Provider", "example": "360"},
    )
    ai_json_max_tokens: int = Field(
        default=8192,
        validation_alias="AI_JSON_MAX_TOKENS",
        description="Max tokens for AI JSON completion calls.",
        json_schema_extra={"group": "AI Provider"},
    )
    ai_json_disable_thinking: bool = Field(
        default=True,
        validation_alias="AI_JSON_DISABLE_THINKING",
        description="Disable provider 'thinking' mode for AI JSON completion calls.",
        json_schema_extra={"group": "AI Provider"},
    )
    ai_daily_limit_usd: int | None = Field(
        default=2,
        validation_alias="AI_DAILY_LIMIT_USD",
        description="Daily AI spend limit in USD (None to disable).",
        json_schema_extra={"group": "AI Provider"},
    )
    # Deterministic decoding for OCR/extraction (#989): a fixed seed makes the
    # provider decode reproducibly so the same statement does not sometimes
    # reconcile and sometimes not. Set AI_JSON_SEED= (empty) to omit it for
    # providers that reject the field.
    # Off by default: Z.AI/GLM validates request params strictly and `seed` is
    # NOT accepted by all models (e.g. glm-4.6v, the default vision/OCR model,
    # returns HTTP 400 for it) — sending it unconditionally would break vision
    # extraction. Opt in only for seed-supporting models (e.g. GLM-5.1).
    # Determinism otherwise rests on temperature=0 / do_sample=false plus the
    # balance-aware self-consistency retry (#989).
    ai_json_seed: int | None = Field(
        default=None,
        validation_alias="AI_JSON_SEED",
        description="Fixed decoding seed for reproducible extraction; off by default (only set for seed-supporting models).",
        json_schema_extra={"group": "AI Provider"},
    )

    # Balance-aware self-consistency (#989 Step B): when a bank statement's
    # running-balance chain fails to reconcile, re-extract up to this many times
    # and keep the first reconciling result before routing to `uploaded`. When a
    # seed is configured (off by default) each attempt varies it; otherwise
    # retries rely on provider-side variance. 1 disables retry (single-shot).
    # Only failing parses retry, so the average cost increase is bounded.
    ai_extract_max_attempts: int = Field(
        default=2,
        ge=1,
        le=5,
        validation_alias="AI_EXTRACT_MAX_ATTEMPTS",
        description="Max balance-aware re-extract attempts for bank statements (1 disables retry).",
        json_schema_extra={"group": "AI Provider"},
    )

    # LLM provider secret encryption (EPIC-023): project-level symmetric key(s)
    # used to encrypt provider API keys at rest in the database (DB-backed
    # provider config). Comma-separated Fernet keys, newest first; decryption
    # tries all (MultiFernet) so rotation is a single pass — prepend a new key,
    # re-encrypt every stored secret, then drop the old key. Empty disables
    # DB-backed provider storage (env/Vault provider config still works).
    llm_encryption_keys: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_ENCRYPTION_KEYS", "LLM_ENCRYPTION_KEY"),
        description=(
            "Comma-separated Fernet keys (urlsafe base64, 32 bytes) for encrypting LLM "
            "provider API keys at rest; newest first. Empty disables DB-backed provider "
            "storage. Rotate by prepending a new key and re-encrypting all secrets."
        ),
        json_schema_extra={"group": "AI Provider", "vault": True},
    )

    @field_validator("ai_json_seed", mode="before")
    @classmethod
    def _empty_seed_is_none(cls, value: object) -> object:
        """Treat an empty/whitespace AI_JSON_SEED as omitted (None).

        Pydantic cannot parse "" as int, so an empty env value would otherwise
        raise at startup and the seed could never actually be omitted via env.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _require_telemetry_contract_in_deployed_envs(self) -> "Settings":
        """Fast-fail when a deployed env ships telemetry without the contract.

        In staging/production, if OTEL export is enabled, the resource MUST carry a
        ``deployment.environment`` tag (issued by infra2 at deploy — see
        repo/docs/ssot/core.environments.md#telemetry-identity). This catches the
        "untagged production telemetry" class before it reaches SigNoz. Non-deployed
        environments (local/CI/preview) and telemetry-off deploys are exempt, so
        this never trips local, tests, or a SigNoz-less deploy.
        """
        if self.environment.strip().lower() not in PROTECTED_ENVIRONMENTS:
            return self
        if not self.otel_exporter_otlp_endpoint:
            return self
        attrs = parse_key_value_pairs(self.otel_resource_attributes)
        if "deployment.environment" not in attrs:
            raise ValueError(
                "Telemetry contract violation: OTEL export is enabled in a deployed "
                "environment but OTEL_RESOURCE_ATTRIBUTES has no "
                "deployment.environment tag. infra2 must issue it; see "
                "repo/docs/ssot/core.environments.md#telemetry-identity."
            )
        return self

    # S3 optional settings
    s3_region: str = Field(
        default="us-east-1",
        description="S3 region.",
        json_schema_extra={"group": "S3 / MinIO Storage"},
    )
    s3_presign_expiry_seconds: int = Field(
        default=300,
        description="Presigned URL TTL (seconds) for general S3 access.",
        json_schema_extra={"group": "S3 / MinIO Storage", "example": "900"},
    )
    statement_review_presign_expiry_seconds: int = Field(
        default=120,
        ge=30,
        le=600,
        validation_alias="STATEMENT_REVIEW_PRESIGN_EXPIRY_SECONDS",
        description="Short-lived PDF preview URL TTL for Stage 1 statement review.",
        json_schema_extra={"group": "S3 / MinIO Storage"},
    )

    # Observability (optional)
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None,
        validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT",
        description="OTLP exporter endpoint. Optional: set in production to ship logs to SigNoz.",
        json_schema_extra={
            "group": "Observability",
            "vault": True,
            "example": "http://platform-signoz-otel-collector:4318",
        },
    )
    otel_service_name: str = Field(
        default="finance-report-backend",
        validation_alias="OTEL_SERVICE_NAME",
        description="OpenTelemetry service name.",
        json_schema_extra={"group": "Observability", "vault": True},
    )
    otel_resource_attributes: str | None = Field(
        default=None,
        validation_alias="OTEL_RESOURCE_ATTRIBUTES",
        description="OpenTelemetry resource attributes (comma-separated key=value pairs).",
        json_schema_extra={
            "group": "Observability",
            "vault": True,
            "example": "deployment.environment=development",
        },
    )

    # Feature Flags for AI-Driven Pipeline (EPIC-018)
    enable_ai_reconciliation: bool = Field(
        default=False,
        validation_alias="ENABLE_AI_RECONCILIATION",
        description=("EPIC-018: enable AI-assisted reconciliation scoring (default false, opt-in to avoid API costs)."),
        json_schema_extra={"group": "Feature Flags"},
    )
    enable_ai_classification: bool = Field(
        default=False,
        description=(
            "EPIC-018: enable AI-assisted transaction classification suggestions "
            "(default false, opt-in to avoid API costs)."
        ),
        validation_alias="ENABLE_AI_CLASSIFICATION",
        json_schema_extra={"group": "Feature Flags"},
    )

    # Storage Sweep
    enable_storage_sweep: bool = Field(
        default=True,
        description=(
            "Enable periodic background sweep for orphaned S3 objects. Set to false "
            "in test/CI environments to suppress background S3 network calls."
        ),
        validation_alias="ENABLE_STORAGE_SWEEP",
        json_schema_extra={"group": "Feature Flags"},
    )
    storage_sweep_grace_period_hours: int = Field(
        default=24,
        ge=1,
        description=(
            "Grace period (hours) before an orphaned S3 object is eligible for the "
            "storage sweep. Objects younger than this are never deleted, to avoid "
            "racing with in-progress uploads (issue #356, default 24h)."
        ),
        validation_alias="STORAGE_SWEEP_GRACE_PERIOD_HOURS",
        json_schema_extra={"group": "Feature Flags"},
    )
    storage_sweep_interval_seconds: int = Field(
        default=86400,
        ge=1,
        description=("Interval (seconds) between orphaned-S3-object sweep runs (issue #356, default 86400s = daily)."),
        validation_alias="STORAGE_SWEEP_INTERVAL_SECONDS",
        json_schema_extra={"group": "Feature Flags"},
    )

    # Deployment metadata
    git_commit_sha: str = Field(
        default="unknown",
        validation_alias="GIT_COMMIT_SHA",
        description="Deployment commit SHA (set by CI, not manually).",
        json_schema_extra={"group": "Deployment metadata"},
    )

    # Rate Limiting (global API protection)
    api_rate_limit_requests: int = Field(
        default=300,
        ge=1,
        validation_alias="API_RATE_LIMIT_REQUESTS",
        description=(
            "Global API rate-limit request count (applies to all endpoints except "
            "/health, /ping, /docs). Default 300 allows E2E test suites and power users."
        ),
        json_schema_extra={"group": "Rate Limiting"},
    )
    api_rate_limit_window: int = Field(
        default=60,
        ge=1,
        validation_alias="API_RATE_LIMIT_WINDOW",
        description="Global API rate-limit window in seconds.",
        json_schema_extra={"group": "Rate Limiting"},
    )
    register_rate_limit_requests: int = Field(
        default=10,
        ge=1,
        validation_alias="REGISTER_RATE_LIMIT_REQUESTS",
        description=(
            "Per-IP registration rate-limit request count on /api/auth/register. "
            "Default 10/600s is strict; set to 10000 in test envs."
        ),
        json_schema_extra={"group": "Rate Limiting"},
    )
    register_rate_limit_window: int = Field(
        default=600,
        ge=1,
        validation_alias="REGISTER_RATE_LIMIT_WINDOW",
        description="Per-IP registration rate-limit window in seconds.",
        json_schema_extra={"group": "Rate Limiting"},
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
                "glm-5-turbo",
                "glm-5",
            ],
        )

    @cached_property
    def vision_fallback_models(self) -> list[str]:
        """Parse vision-path fallback models from env string or use defaults.

        The vision/OCR path sends image content, so its fallbacks must be
        vision-capable; the text-only ``FALLBACK_MODELS`` are intentionally not
        reused here (#1034). The default keeps a single secondary vision model so
        a non-retryable failure of the primary vision model does not fail the
        whole upload.
        """
        return parse_comma_list(
            self.vision_fallback_models_str,
            [
                "glm-4.5v",
            ],
        )

    @cached_property
    def llm_encryption_key_list(self) -> list[str]:
        """Parsed Fernet keys for provider-secret encryption (newest first).

        Empty when ``LLM_ENCRYPTION_KEYS`` is unset, which means DB-backed
        provider secrets cannot be stored (see ``src/llm/common/secrets.py``).
        """
        return parse_comma_list(self.llm_encryption_keys, [])


settings = Settings()
