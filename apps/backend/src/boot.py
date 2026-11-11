"""Unified environment bootloader for startup, CI dry-run, and smoke checks."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Any

from infra2_sdk.runtime.config_schema import (
    EnvironmentConflictError,
    environment_manifest_from_model,
    validate_environment,
)
from infra2_sdk.runtime.health import DependencyStatus

from src.config import ENV_SOURCE_CLASSES, PROTECTED_ENVIRONMENTS, Settings, settings
from src.observability import get_logger
from src.runtime import (
    DEPENDENCY_MANIFEST,
    AnalyticsCheck,
    DatabaseCheck,
    EnvTier,
    LlmCheck,
    MarketDataCheck,
    ObjectStorageCheck,
    RedisCheck,
    TelemetryCheck,
    WorkflowEngineCheck,
    resolve_env_tier,
)

logger = get_logger(__name__)

DEVELOPMENT_SECRET_KEY = "dev_secret_key_change_in_prod"
DEVELOPMENT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report"
DEVELOPMENT_S3_SECRET_KEY = "minio_local_secret"
LOCAL_ENVIRONMENTS = frozenset({"development", "test", "ci"})

_PROBE_METHODS = {
    "database": "_check_database",
    "object_storage": "_check_s3",
    "llm": "_check_openrouter",
    "cache": "_check_cache",
    "workflow_engine": "_check_workflow_engine",
    "telemetry": "_check_telemetry",
    "analytics": "_check_analytics",
    "market_data": "_check_market_data",
}
_SAFE_PRINT_FIELDS = (
    "debug",
    "environment",
    "base_currency",
    "ai_provider",
    "ai_base_url",
    "large_model",
    "small_model",
    "multimodal_model",
    "s3_endpoint",
    "s3_bucket",
    "cors_origin_regex",
    "otel_exporter_otlp_endpoint",
    "otel_service_name",
)
_SENSITIVE_PRINT_FIELDS = ("database_url", "ai_api_key", "s3_access_key", "s3_secret_key")


class BootMode(str, Enum):
    CRITICAL = "critical"
    FULL = "full"
    DRY_RUN = "dry-run"


@dataclass
class ServiceStatus:
    service: str
    status: str
    message: str
    duration_ms: float = 0.0


async def _probe_status(service: str, adapter: Any, *, include_duration: bool = True) -> ServiceStatus:
    result = await adapter.probe()
    ok = getattr(result, "present", result.status is DependencyStatus.PRESENT)
    return ServiceStatus(
        service,
        "ok" if ok else "error",
        result.detail,
        result.duration_ms if include_duration else 0.0,
    )


class Bootloader:
    """Validate runtime configuration and external dependency reachability."""

    @staticmethod
    def _required_checks(tier: EnvTier) -> tuple[dict[str, str], list[str]]:
        required = DEPENDENCY_MANIFEST.required_for(tier)
        probed = {name: _PROBE_METHODS[name] for name in required if name in _PROBE_METHODS}
        return probed, sorted(required - probed.keys())

    @staticmethod
    async def validate(mode: BootMode = BootMode.CRITICAL, tier: EnvTier | None = None) -> bool:
        if tier is None:
            tier = resolve_env_tier(
                settings.environment, github_actions=os.getenv("GITHUB_ACTIONS", "").lower() == "true"
            )
        logger.info("Bootloader starting validation", mode=mode.value, tier=tier.value)

        if not Bootloader._check_static_config():
            if mode == BootMode.CRITICAL:
                logger.critical("Static configuration check failed. Refusing to start.")
                sys.exit(1)
            return False

        if mode == BootMode.DRY_RUN:
            print("✅ Dry-run configuration check passed.")
            return True

        results = [await Bootloader._check_database()]
        if mode == BootMode.FULL:
            probed, unprobed = Bootloader._required_checks(tier)
            for name, method_name in sorted(probed.items()):
                if name != "database":
                    results.append(await getattr(Bootloader, method_name)())
            for name in unprobed:
                logger.warning(
                    "Declared-required dependency has no probe adapter yet (#1580); presence not asserted",
                    service=name,
                    tier=tier.value,
                )

        passed = True
        for res in results:
            if res.status == "error":
                passed = False
                logger.error(
                    "Service check failed", service=res.service, error=res.message, duration_ms=res.duration_ms
                )
            elif res.status == "warning":
                logger.warning(
                    "Service check warning", service=res.service, message=res.message, duration_ms=res.duration_ms
                )
            else:
                logger.info("Service check passed", service=res.service, duration_ms=res.duration_ms)

        if not passed:
            if mode == BootMode.CRITICAL:
                logger.critical("Critical service checks failed. Application cannot start.")
                sys.exit(1)
            return False

        logger.info("Bootloader validation successful")
        return True

    @staticmethod
    def print_config() -> None:
        if os.getenv("DEBUG", "").lower() not in ("true", "1", "yes"):
            return
        print("\n" + "=" * 60 + "\nConfig loaded (DEBUG mode)\n" + "=" * 60)
        for field in _SAFE_PRINT_FIELDS:
            value = getattr(settings, field, None)
            if value is not None:
                print(f"  {field}: {value}")
        print("")
        for field in _SENSITIVE_PRINT_FIELDS:
            print(f"  {field}: {'set' if getattr(settings, field, None) else 'not set'}")
        print("\nFields using defaults:")
        defaults_used = [f for f in _SAFE_PRINT_FIELDS if not os.getenv(f.upper())]
        print("\n".join(f"  - {f}" for f in defaults_used) if defaults_used else "  (none)")
        print("=" * 60 + "\n")

    @staticmethod
    def _is_protected_runtime(environment: str) -> bool:
        normalized = environment.strip().lower()
        if normalized in PROTECTED_ENVIRONMENTS or normalized not in LOCAL_ENVIRONMENTS:
            return True
        app_url = str(getattr(settings, "next_public_app_url", "") or "").strip().lower()
        return app_url.startswith("https://") and "localhost" not in app_url and "127.0.0.1" not in app_url

    @staticmethod
    def _assert_sdk_environment(*, is_protected: bool = False) -> None:
        manifest = environment_manifest_from_model(
            Settings, source="apps/backend/src/config.py::Settings", overrides=ENV_SOURCE_CLASSES
        )
        effective_environ = dict(os.environ)
        for field in manifest.fields:
            if not field.injected:
                continue
            names = (field.env, *field.aliases)
            if field.empty_ok:
                if not any(effective_environ.get(name, "").strip() for name in names):
                    effective_environ[field.env] = "__empty_ok__"
                continue
            val = getattr(settings, field.field, None)
            if isinstance(val, str):
                if not val.strip():
                    for candidate in names:
                        effective_environ.pop(candidate, None)
                elif field.env not in effective_environ:
                    effective_environ[field.env] = val.strip()
            elif val is None:
                for candidate in names:
                    effective_environ.pop(candidate, None)
            else:
                effective_environ.setdefault(field.env, str(val))
        validation = validate_environment(manifest, effective_environ, require_injected=is_protected)
        if validation.missing:
            raise RuntimeError(
                f"environment lacks {len(validation.missing)} value(s) manifest declares: "
                f"{', '.join(validation.missing)} -- names only; the deployment must inject them (#759)"
            )

    @staticmethod
    def _check_static_config() -> bool:
        try:
            database_url = settings.database_url
            environment = str(getattr(settings, "environment", "")).lower()
            is_protected = Bootloader._is_protected_runtime(environment)
            Bootloader._assert_sdk_environment(is_protected=environment.strip() in PROTECTED_ENVIRONMENTS)
            if is_protected:
                secret_key = getattr(settings, "secret_key", "")
                if not isinstance(secret_key, str) or not secret_key.strip():
                    logger.error("SECRET_KEY is required in protected environments", environment=environment)
                    return False
                normalized_secret = secret_key.strip()
                checks = (
                    (normalized_secret == DEVELOPMENT_SECRET_KEY, "Default development SECRET_KEY is forbidden"),
                    (len(normalized_secret.encode("utf-8")) < 32, "SECRET_KEY must be at least 32 bytes"),
                    (
                        str(database_url).strip() == DEVELOPMENT_DATABASE_URL,
                        "Default development DATABASE_URL is forbidden",
                    ),
                    (
                        str(getattr(settings, "s3_secret_key", "")).strip() == DEVELOPMENT_S3_SECRET_KEY,
                        "Default development S3_SECRET_KEY is forbidden",
                    ),
                )
                for failed, message in checks:
                    if failed:
                        logger.error(message, environment=environment)
                        return False
            return True
        except EnvironmentConflictError as exc:
            logger.error("Environment variable conflict detected", error=str(exc))
            return False
        except Exception as exc:
            logger.error("Configuration load failed", error=str(exc))
            return False

    @staticmethod
    async def _check_database() -> ServiceStatus:
        return await _probe_status("database", DatabaseCheck(settings.database_url))

    @staticmethod
    async def _check_s3() -> ServiceStatus:
        return await _probe_status(
            "minio",
            ObjectStorageCheck(
                endpoint=settings.s3_endpoint,
                access_key=settings.s3_access_key,
                secret_key=settings.s3_secret_key,
                region=settings.s3_region,
                bucket=settings.s3_bucket,
            ),
        )

    @staticmethod
    async def _check_ai_provider() -> ServiceStatus:
        return await _probe_status(
            "ai_provider",
            LlmCheck(
                api_key=getattr(settings, "ai_api_key", None),
                provider=settings.ai_provider,
                small_model=settings.small_model,
                multimodal_model=settings.multimodal_model,
            ),
            include_duration=False,
        )

    _check_openrouter = _check_ai_provider

    @staticmethod
    async def _check_cache() -> ServiceStatus:
        return await _probe_status("cache", RedisCheck(url=settings.redis_url))

    @staticmethod
    async def _check_workflow_engine() -> ServiceStatus:
        return await _probe_status("workflow_engine", WorkflowEngineCheck(api_url=settings.prefect_api_url))

    @staticmethod
    async def _check_telemetry() -> ServiceStatus:
        return await _probe_status("telemetry", TelemetryCheck(endpoint=settings.otel_exporter_otlp_endpoint))

    @staticmethod
    async def _check_analytics() -> ServiceStatus:
        return await _probe_status("analytics", AnalyticsCheck(api_url=settings.openpanel_api_url))

    @staticmethod
    async def _check_market_data() -> ServiceStatus:
        return await _probe_status(
            "market_data", MarketDataCheck(timeout_seconds=settings.market_data_yahoo_timeout_seconds)
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", type=str, default="full", choices=["critical", "full", "dry-run"])
    args = parser.parse_args()
    print(f"Bootloader: Running validation cycle (mode={args.mode})")
    try:
        success = asyncio.run(Bootloader.validate(BootMode(args.mode)))
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
    print("✅ Validation check passed." if success else "❌ Validation check failed.")
    sys.exit(0 if success else 1)
