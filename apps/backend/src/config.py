"""Application configuration using Pydantic Settings."""

import os
from functools import cached_property
from typing import Any, Literal

from infra2_sdk.runtime.llm import LlmSettings
from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

PROTECTED_ENVIRONMENTS = frozenset({"staging", "production"})
EMPTY_FALLBACK_FIELDS = frozenset(
    """
    ai_api_key cors_origins_str next_public_app_url otel_resource_attributes
    api_rate_limit_requests api_rate_limit_window register_rate_limit_requests
    llm_encryption_keys s3_public_access_key s3_public_secret_key
    reconciliation_auto_accept_threshold reconciliation_review_threshold
    """.split()
)

_GROUPS = {
    "db": "Database",
    "s3": "S3 / MinIO Storage",
    "sec": "Security",
    "ai": "AI Provider",
    "app": "App Settings",
    "obs": "Observability",
    "ff": "Feature Flags",
    "dep": "Deployment metadata",
    "rl": "Rate Limiting",
}

_FIELD_SPECS: dict[str, tuple[str, set[str], str]] = {}
for _line in """
database_url|db|i,na|Async SQLAlchemy database URL. Use postgresql+asyncpg:// for async FastAPI compatibility.
db_pool_size|db||DB connection pool size (optional tuning for production).
db_pool_max_overflow|db||DB connection pool max overflow (optional tuning for production).
s3_endpoint|s3|i,na|S3 / MinIO endpoint used for storing uploaded statement files.
s3_access_key|s3|i|S3 / MinIO access key.
s3_secret_key|s3|i|S3 / MinIO secret key.
s3_bucket|s3|i,na|S3 / MinIO bucket name for uploaded statements.
s3_public_endpoint|s3|i|Publicly reachable S3 endpoint for AI services. REQUIRED in production if S3_ENDPOINT is internal (e.g. http://minio:9000). Some AI providers need publicly accessible URLs to download statement PDFs for parsing. If not set, the system sends file_content (Base64) when available and only falls back to the S3 file_url when no content is provided.
s3_public_access_key|s3|i|Public S3 access key (falls back to internal S3 settings when unset).
s3_public_secret_key|s3|i|Public S3 secret key (falls back to internal S3 settings when unset).
s3_public_bucket|s3|i|Public S3 bucket (falls back to internal S3 settings when unset).
secret_key|sec|i|Application secret key. CRITICAL: must be set to a secure random value in production via Vault.
jwt_algorithm|sec||JWT signing algorithm.
access_token_expire_minutes|sec||Access token lifetime in minutes.
trust_proxy|sec||Trust X-Forwarded-For headers from reverse proxies.
ai_provider|ai|i|AI provider id. Required for document extraction and the AI advisor (Z.AI/GLM defaults).
ai_api_key|ai|i,ac:AI_API_KEY+ZAI_API_KEY|AI provider API key (empty key = AI features disabled). Settings also reads the old name ZAI_API_KEY.
environment|app|i,ac:ENVIRONMENT+ENV|Logical environment name (used to differentiate environments).
debug|app|na|Enable debug mode.
base_currency|app|na|Base reporting currency (ISO 4217).
market_data_lazy_fetch_enabled|app||Report-side FX lazy resolution. Set to false to prevent outbound Yahoo Finance calls.
market_data_fx_bridge_currency|app||Bridge currency used for FX cross-rate resolution.
market_data_yahoo_timeout_seconds|app||Timeout (seconds) for outbound Yahoo Finance market-data calls.
redis_url|app||Optional Redis URL for staging/production background coordination.
next_public_app_url|app|i|Backend reference to the frontend URL; should match the frontend NEXT_PUBLIC_APP_URL and is used by backend components when they link back to the frontend app.
cors_origins_str|sec|i,al:CORS_ORIGINS|Comma-separated CORS origins, e.g. http://localhost:3000,http://localhost:3001.
cors_origin_regex|sec|na|CORS origin regex for dynamic subdomains (PR deployments and staging).
ai_base_url|ai||AI provider base URL (provider-neutral; default targets Z.AI/GLM).
ai_chat_completions_path|ai||Chat completions path appended to the AI base URL.
large_model|ai||Large-role AI model id for user-facing answers (advisor chat). Unset: the infra2 SDK default; set it only to customize production.
small_model|ai||Small-role AI model id for text work: JSON extraction, statement summaries and transaction classification. Unset: the infra2 SDK default; set it only to customize production.
multimodal_model|ai||Multimodal-role AI model id for vision and OCR (image, PDF and file input). Unset: the infra2 SDK default; set it only to customize production.
prefect_api_url|ai||EPIC-019: set to the Prefect API URL to run upload->report parsing as durable Prefect flow runs (staging/prod and per-PR ephemeral Prefect). Leave unset for CI/local/preview -> in-process asyncio fallback (no Prefect needed).
ai_json_timeout_seconds|ai||Timeout (seconds) for AI JSON completion calls.
ai_json_max_tokens|ai||Max tokens for AI JSON completion calls.
ai_json_disable_thinking|ai||Request disabled thinking for AI JSON calls; reasoning-only models use their lowest supported effort.
ai_json_seed|ai||Fixed decoding seed for reproducible extraction; off by default (only set for seed-supporting models).
ai_extract_max_attempts|ai||Max balance-aware re-extract attempts for bank statements (1 disables retry).
llm_encryption_keys|ai|i|Comma-separated Fernet keys (urlsafe base64, 32 bytes) for encrypting LLM provider API keys at rest; newest first. Empty disables DB-backed provider storage. Rotate by prepending a new key and re-encrypting all secrets.
llm_cassette_engage|ai||Engage offline LLM cassette replay layer.
llm_cassette_refresh|ai||Refresh recorded LLM cassettes in local runs.
llm_live|ai||Force live LLM provider calls.
s3_region|s3|na|S3 region.
s3_presign_expiry_seconds|s3|na|Presigned URL TTL (seconds) for general S3 access.
statement_review_presign_expiry_seconds|s3||Short-lived PDF preview URL TTL for Stage 1 statement review.
otel_exporter_otlp_endpoint|obs|i|OTLP exporter endpoint. Optional: set in production to ship telemetry to the OTLP collector (infra2-owned).
otel_service_name|obs|i|OpenTelemetry service name.
otel_resource_attributes|obs|i|OpenTelemetry resource attributes (comma-separated key=value pairs).
openpanel_client_id|obs||Per-env OpenPanel project client-id for server-side events (empty = analytics off).
openpanel_api_url|obs||OpenPanel API base URL (e.g. https://openpanel.zitian.party/api).
openpanel_environment|obs||Canonical OpenPanel environment label (falls back to `environment`).
enable_ai_reconciliation|ff||EPIC-018: enable AI-assisted reconciliation scoring (default true; a user can turn it off in the AI settings).
reconciliation_auto_accept_threshold|ff||Optional override for reconciliation auto-accept score threshold.
reconciliation_review_threshold|ff||Optional override for reconciliation pending-review score threshold.
enable_ai_classification|ff||EPIC-018: enable AI-assisted transaction classification suggestions (default true). A user can turn it off in the AI settings.
auto_accept_ai_suggestions|ff||Post every row of a statement without a person: the system accepts the AI suggestions at or above the review score, and a general account takes a row that the AI could not place (default true). A user can turn it off in the AI settings. Set false to turn it off for all users: this flag is a ceiling over the setting of each user. A compose file that does not set this variable keeps the code default. Needs enable_ai_classification.
statement_disposition_mode|ff||Versioned statement-disposition rollout mode. It controls command application only; the shared policy still computes every decision.
enable_storage_sweep|ff||Enable periodic background sweep for orphaned S3 objects. Set to false in test/CI environments to suppress background S3 network calls.
storage_sweep_grace_period_hours|ff||Grace period (hours) before an orphaned S3 object is eligible for the storage sweep. Objects younger than this are never deleted, to avoid racing with in-progress uploads (issue #356, default 24h).
storage_sweep_interval_seconds|ff||Interval (seconds) between orphaned-S3-object sweep runs (issue #356, default 86400s = daily).
git_commit_sha|dep||Deployment commit SHA (set by CI, not manually).
api_rate_limit_requests|rl||Global API rate-limit request count (applies to all endpoints except /health, /ping, /docs). Default 300 allows E2E test suites and power users.
api_rate_limit_window|rl||Global API rate-limit window in seconds.
register_rate_limit_requests|rl||Per-IP registration rate-limit request count on /api/auth/register. Default 10/600s is strict; set to 10000 in test envs.
register_rate_limit_window|rl||Per-IP registration rate-limit window in seconds.
""".strip().splitlines():
    _n, _g, _fl, _d = _line.split("|", 3)
    _FIELD_SPECS[_n] = (_GROUPS[_g], set(filter(None, _fl.split(","))), _d)


def _f(
    name: str, default: Any, *, ex: str | None = None, ge: int | None = None, le: int | None = None, **extra: Any
) -> Any:
    group, flags, desc = _FIELD_SPECS[name]
    schema_extra: dict[str, Any] = {"group": group}
    if "i" in flags:
        schema_extra["injected"] = True
    if ex is not None:
        schema_extra["example"] = ex
    schema_extra.update(extra)
    kw: dict[str, Any] = {"default": default, "description": desc, "json_schema_extra": schema_extra}
    ac = next((x[3:] for x in flags if x.startswith("ac:")), None)
    al = next((x[3:] for x in flags if x.startswith("al:")), None)
    if ac is not None:
        kw["validation_alias"] = AliasChoices(*ac.split("+"))
    elif al is not None:
        kw["validation_alias"] = al
    elif "na" not in flags:
        kw["validation_alias"] = name.upper()
    if ge is not None:
        kw["ge"] = ge
    if le is not None:
        kw["le"] = le
    return Field(**kw)


def _extract_env_candidate_names(field: FieldInfo, field_name: str) -> list[str]:
    alias = field.validation_alias
    if isinstance(alias, AliasChoices):
        return [c for c in alias.choices if isinstance(c, str)]
    return [alias] if isinstance(alias, str) else [field_name]


def _resolve_safe_empty_value(
    source: EnvSettingsSource, field: FieldInfo, field_name: str
) -> tuple[Any, str, bool] | None:
    if field_name not in EMPTY_FALLBACK_FIELDS:
        return None
    env_map = getattr(source, "env_vars", None)
    for env_name in _extract_env_candidate_names(field, field_name):
        val = (
            (env_map.get(env_name.lower()) if env_name.lower() in env_map else env_map.get(env_name))
            if env_map is not None
            else None
        )
        if val is None:
            val = os.environ.get(env_name)
        if val is not None and str(val).strip() != "":
            return val, env_name, False
    return None, field_name, False


class SafeEnvSettingsSource(EnvSettingsSource):
    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return _resolve_safe_empty_value(self, field, field_name) or super().get_field_value(field, field_name)


class SafeDotEnvSettingsSource(DotEnvSettingsSource):
    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return _resolve_safe_empty_value(self, field, field_name) or super().get_field_value(field, field_name)


def parse_comma_list(value: str | list[str] | None, default: list[str]) -> list[str]:
    if value is None:
        return default
    return value if isinstance(value, list) else [item.strip() for item in value.split(",") if item.strip()]


def parse_key_value_pairs(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    pairs: dict[str, str] = {}
    for item in value.split(","):
        if "=" in item:
            k, v = (p.strip() for p in item.split("=", 1))
            if k and v:
                pairs[k] = v
    return pairs


_SDK_LLM_DEFAULTS = LlmSettings()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls, settings_cls: Any, init_settings: Any, env_settings: Any, dotenv_settings: Any, file_secret_settings: Any
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        _ = env_settings
        return (
            init_settings,
            SafeEnvSettingsSource(settings_cls),
            SafeDotEnvSettingsSource(
                settings_cls,
                env_file=getattr(dotenv_settings, "env_file", None),
                env_file_encoding=getattr(dotenv_settings, "env_file_encoding", "utf-8"),
            ),
            file_secret_settings,
        )

    database_url: str = _f(
        "database_url",
        "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report",
        ex="postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report",
    )
    db_pool_size: int = _f("db_pool_size", 5, ge=1)
    db_pool_max_overflow: int = _f("db_pool_max_overflow", 10, ge=0)
    s3_endpoint: str = _f("s3_endpoint", "http://127.0.0.1:9000", ex="http://localhost:9000")
    s3_access_key: str = _f("s3_access_key", "minio")
    s3_secret_key: str = _f("s3_secret_key", "minio_local_secret", ex="<YOUR_S3_SECRET_KEY>")
    s3_bucket: str = _f("s3_bucket", "statements")
    s3_public_endpoint: str | None = _f("s3_public_endpoint", None, ex="https://your-public-s3-endpoint.example.com")
    s3_public_access_key: str | None = _f("s3_public_access_key", None)
    s3_public_secret_key: str | None = _f("s3_public_secret_key", None)
    s3_public_bucket: str | None = _f("s3_public_bucket", None)
    secret_key: str = _f(
        "secret_key", "dev_secret_key_change_in_prod", ex="generate_a_secure_token_for_production_here"
    )
    jwt_algorithm: str = _f("jwt_algorithm", "HS256")
    access_token_expire_minutes: int = _f("access_token_expire_minutes", 1440)
    trust_proxy: bool = _f("trust_proxy", False)
    ai_provider: str = _f("ai_provider", "zai")
    ai_api_key: str = _f("ai_api_key", "", store_key="ZAI_API_KEY")
    environment: str = _f("environment", "development", extra_keys=["ENV"])
    debug: bool = _f("debug", False, ex="true")
    base_currency: str = _f("base_currency", "SGD")
    market_data_lazy_fetch_enabled: bool = _f("market_data_lazy_fetch_enabled", True)
    market_data_fx_bridge_currency: str = _f("market_data_fx_bridge_currency", "USD")
    market_data_yahoo_timeout_seconds: int = _f("market_data_yahoo_timeout_seconds", 5, ge=1, le=30)
    redis_url: str | None = _f("redis_url", None)
    next_public_app_url: str = _f("next_public_app_url", "http://localhost:3000")
    cors_origins_str: str | None = _f("cors_origins_str", None, ex="http://localhost:3000,http://localhost:3001")
    cors_origin_regex: str = _f("cors_origin_regex", "^$", ex='r"https://report(-pr-\\d+|-staging)?\\.zitian\\.party"')
    ai_base_url: str = _f("ai_base_url", "https://api.z.ai/api/coding/paas/v4")
    ai_chat_completions_path: str = _f("ai_chat_completions_path", "/chat/completions")
    large_model: str = _f("large_model", _SDK_LLM_DEFAULTS.large_model)
    small_model: str = _f("small_model", _SDK_LLM_DEFAULTS.small_model)
    multimodal_model: str = _f("multimodal_model", _SDK_LLM_DEFAULTS.multimodal_model)
    prefect_api_url: str | None = _f("prefect_api_url", None)
    ai_json_timeout_seconds: float = _f("ai_json_timeout_seconds", 360.0, ex="360")
    ai_json_max_tokens: int = _f("ai_json_max_tokens", 32768)
    ai_json_disable_thinking: bool = _f("ai_json_disable_thinking", True)
    ai_json_seed: int | None = _f("ai_json_seed", None)
    ai_extract_max_attempts: int = _f("ai_extract_max_attempts", 2, ge=1, le=5)
    llm_encryption_keys: str = _f("llm_encryption_keys", "")
    llm_cassette_engage: bool = _f("llm_cassette_engage", False)
    llm_cassette_refresh: bool = _f("llm_cassette_refresh", False)
    llm_live: bool = _f("llm_live", False)
    s3_region: str = _f("s3_region", "us-east-1")
    s3_presign_expiry_seconds: int = _f("s3_presign_expiry_seconds", 300, ex="900")
    statement_review_presign_expiry_seconds: int = _f("statement_review_presign_expiry_seconds", 120, ge=30, le=600)
    otel_exporter_otlp_endpoint: str | None = _f(
        "otel_exporter_otlp_endpoint", None, ex="http://platform-signoz-otel-collector:4318"
    )
    otel_service_name: str = _f("otel_service_name", "finance-report-backend")
    otel_resource_attributes: str | None = _f("otel_resource_attributes", None, ex="deployment.environment=development")
    openpanel_client_id: str = _f("openpanel_client_id", "")
    openpanel_api_url: str = _f("openpanel_api_url", "")
    openpanel_environment: str = _f("openpanel_environment", "")
    enable_ai_reconciliation: bool = _f("enable_ai_reconciliation", True)
    reconciliation_auto_accept_threshold: int | None = _f("reconciliation_auto_accept_threshold", None)
    reconciliation_review_threshold: int | None = _f("reconciliation_review_threshold", None)
    enable_ai_classification: bool = _f("enable_ai_classification", True)
    auto_accept_ai_suggestions: bool = _f("auto_accept_ai_suggestions", True)
    statement_disposition_mode: Literal["off", "observe", "enforce"] = _f("statement_disposition_mode", "enforce")
    enable_storage_sweep: bool = _f("enable_storage_sweep", True)
    storage_sweep_grace_period_hours: int = _f("storage_sweep_grace_period_hours", 24, ge=1)
    storage_sweep_interval_seconds: int = _f("storage_sweep_interval_seconds", 86400, ge=1)
    git_commit_sha: str = _f("git_commit_sha", "unknown")
    api_rate_limit_requests: int = _f("api_rate_limit_requests", 300, ge=1)
    api_rate_limit_window: int = _f("api_rate_limit_window", 60, ge=1)
    register_rate_limit_requests: int = _f("register_rate_limit_requests", 10, ge=1)
    register_rate_limit_window: int = _f("register_rate_limit_window", 600, ge=1)

    @field_validator("base_currency", mode="before")
    @classmethod
    def _normalize_base_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator(
        "ai_json_seed",
        "reconciliation_auto_accept_threshold",
        "reconciliation_review_threshold",
        "cors_origins_str",
        "otel_resource_attributes",
        mode="before",
    )
    @classmethod
    def _empty_cors_origins_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator(
        "next_public_app_url",
        "api_rate_limit_requests",
        "api_rate_limit_window",
        "register_rate_limit_requests",
        mode="before",
    )
    @classmethod
    def _empty_rate_limits_use_default(cls, value: object, info: Any) -> object:
        if (isinstance(value, str) and not value.strip()) or value is None:
            return cls.model_fields[info.field_name].default
        return value

    @model_validator(mode="after")
    def _require_telemetry_contract_in_deployed_envs(self) -> "Settings":
        environment = self.environment.strip().lower()
        if environment not in PROTECTED_ENVIRONMENTS or not self.otel_exporter_otlp_endpoint:
            return self
        attrs = parse_key_value_pairs(self.otel_resource_attributes)
        if "deployment.environment" not in attrs:
            raise ValueError(
                "Telemetry contract violation: OTEL export is enabled in a deployed "
                "environment but OTEL_RESOURCE_ATTRIBUTES has no "
                "deployment.environment tag. infra2 must issue it; see "
                "the canonical infra2 environment SSOT."
            )
        declared = attrs["deployment.environment"].strip().lower()
        if declared != environment:
            raise ValueError(
                "Telemetry contract violation: OTEL_RESOURCE_ATTRIBUTES declares "
                f"deployment.environment={declared!r} but the running environment is "
                f"{environment!r} — telemetry would be attributed to the wrong tier "
                "(#1828 G-telemetry-tag-consistent). infra2 issues the tag at deploy; "
                "see the canonical infra2 environment SSOT."
            )
        return self

    @cached_property
    def cors_origins(self) -> list[str]:
        return parse_comma_list(
            self.cors_origins_str, ["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000"]
        )

    @cached_property
    def llm_encryption_key_list(self) -> list[str]:
        return parse_comma_list(self.llm_encryption_keys, [])

    def to_llm_settings(self) -> LlmSettings:
        return LlmSettings(
            provider=self.ai_provider,
            base_url=self.ai_base_url,
            api_key=self.ai_api_key or None,
            large_model=self.large_model,
            small_model=self.small_model,
            multimodal_model=self.multimodal_model,
            chat_completions_path=self.ai_chat_completions_path,
            json_timeout_seconds=self.ai_json_timeout_seconds,
            json_max_tokens=self.ai_json_max_tokens,
            json_disable_thinking=self.ai_json_disable_thinking,
            json_seed=self.ai_json_seed,
            extract_max_attempts=self.ai_extract_max_attempts,
            encryption_keys=tuple(self.llm_encryption_key_list),
        )


settings = Settings()

ENV_SOURCE_CLASSES: dict[str, dict[str, object]] = {
    "database_url": {
        "source": "runtime",
        "sensitive": True,
        "provided_by": "finance_report/postgres:POSTGRES_PASSWORD",
        "composed_from": "postgresql+asyncpg://postgres:{POSTGRES_PASSWORD}@finance_report-postgres{env:ENV_SUFFIX}:5432/finance_report",
    },
    "redis_url": {
        "source": "runtime",
        "sensitive": True,
        "provided_by": "finance_report/redis:PASSWORD",
        "composed_from": "redis://:{PASSWORD}@finance_report-redis{env:ENV_SUFFIX}:6379/0",
    },
    "ai_api_key": {"source": "human", "sensitive": True, "empty_ok": True, "store_key": "ZAI_API_KEY"},
    "git_commit_sha": {"source": "release"},
    **{k: {"source": "runtime", "sensitive": True} for k in ("s3_access_key", "s3_secret_key", "secret_key")},
    **{
        k: {"source": "runtime", "sensitive": True, "empty_ok": True}
        for k in ("s3_public_access_key", "s3_public_secret_key", "llm_encryption_keys")
    },
    **{
        k: {"source": "decision"}
        for k in (
            "environment debug cors_origins_str next_public_app_url s3_endpoint s3_bucket "
            "s3_public_endpoint s3_presign_expiry_seconds prefect_api_url api_rate_limit_requests "
            "otel_exporter_otlp_endpoint otel_service_name otel_resource_attributes openpanel_api_url"
        ).split()
    },
    **{
        k: {"source": "decision", "empty_ok": True}
        for k in ("s3_public_bucket", "openpanel_client_id", "openpanel_environment")
    },
}
