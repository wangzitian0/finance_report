"""
Unified Environment Bootloader.

This module is the SINGLE SOURCE OF TRUTH for environment validation.
It is used by:
1. Application Startup (main.py) -> mode="critical"
2. CI Pipelines (ci.yml) -> mode="dry-run"
3. Smoke Tests (Manual/Cron) -> mode="full" (CLI)
"""

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.config import PROTECTED_ENVIRONMENTS, settings
from src.logger import get_logger

logger = get_logger(__name__)

VAULT_SECRETS_FILE_PATH = "/secrets/.env"
VAULT_SECRETS_STALENESS_THRESHOLD_SECONDS = 3600
DEVELOPMENT_SECRET_KEY = "dev_secret_key_change_in_prod"
DEVELOPMENT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report"
DEVELOPMENT_S3_SECRET_KEY = "minio_local_secret"
# PROTECTED_ENVIRONMENTS is the single source of truth in src.config (imported above).
LOCAL_ENVIRONMENTS = frozenset({"development", "test", "ci"})


class BootMode(str, Enum):
    CRITICAL = "critical"  # DB only (Fast fail for startup)
    FULL = "full"  # DB + S3 + AI (Smoke tests)
    DRY_RUN = "dry-run"  # Static config check only (CI lint)


@dataclass
class ServiceStatus:
    service: str
    status: str  # 'ok', 'warning', 'error', 'skipped'
    message: str
    duration_ms: float = 0.0


class Bootloader:
    """Handles environment validation and service connectivity checks."""

    @staticmethod
    async def validate(mode: BootMode = BootMode.CRITICAL) -> bool:
        """Run validation checks. Returns True if passed, False if failed.

        If mode is CRITICAL, this may call sys.exit(1) on failure.
        """
        logger.info("Bootloader starting validation", mode=mode.value)

        # 1. Static Configuration Check (Always run)
        if not Bootloader._check_static_config():
            if mode == BootMode.CRITICAL:
                logger.critical("Static configuration check failed. Refusing to start.")
                sys.exit(1)
            return False

        if mode == BootMode.DRY_RUN:
            print("✅ Dry-run configuration check passed.")
            return True

        # 2. Connectivity Checks
        results = []

        # Database (Always checked in Critical/Full)
        results.append(await Bootloader._check_database())

        if mode == BootMode.FULL:
            # Add optional services for Full smoke test
            results.append(await Bootloader._check_s3())
            results.append(await Bootloader._check_openrouter())
            results.append(Bootloader._check_vault_secrets())

        # 3. Report Results
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
        """Print loaded configuration if DEBUG is enabled (Gate 2/3 UX)."""
        if os.getenv("DEBUG", "").lower() not in ("true", "1", "yes"):
            return

        print("\n" + "=" * 60)
        print("Config loaded (DEBUG mode)")
        print("=" * 60)

        # Safe fields - values can be displayed in full (non-sensitive)
        safe_fields = [
            "debug",
            "environment",
            "base_currency",
            "ai_provider",
            "ai_base_url",
            "primary_model",
            "ocr_model",
            "vision_model",
            "s3_endpoint",
            "s3_bucket",
            "cors_origin_regex",
            "otel_exporter_otlp_endpoint",
            "otel_service_name",
        ]

        # Sensitive fields - only show "set"/"not set" status
        sensitive_fields = [
            "database_url",
            "ai_api_key",
            "s3_access_key",
            "s3_secret_key",
        ]

        for field in safe_fields:
            value = getattr(settings, field, None)
            if value is not None:
                print(f"  {field}: {value}")

        print("")
        for field in sensitive_fields:
            value = getattr(settings, field, None)
            status = "set" if value else "not set"
            print(f"  {field}: {status}")

        print("\nFields using defaults:")
        env_aliases = {"environment": "ENVIRONMENT"}
        defaults_used = []
        for field in safe_fields:
            env_name = env_aliases.get(field, field.upper())
            if not os.getenv(env_name):
                defaults_used.append(field)

        if defaults_used:
            for field in defaults_used:
                print(f"  - {field}")
        else:
            print("  (none)")

        print("=" * 60 + "\n")

    @staticmethod
    def _is_protected_runtime(environment: str) -> bool:
        """Return True when config should be treated as deployed/protected."""
        normalized = environment.strip().lower()
        if normalized in PROTECTED_ENVIRONMENTS:
            return True
        if normalized not in LOCAL_ENVIRONMENTS:
            return True
        app_url = str(getattr(settings, "next_public_app_url", "") or "").strip().lower()
        return app_url.startswith("https://") and "localhost" not in app_url and "127.0.0.1" not in app_url

    @staticmethod
    def _check_static_config() -> bool:
        """Verify presence of required environment variables."""
        try:
            # Just accessing settings triggers validation
            database_url = settings.database_url
            environment = str(getattr(settings, "environment", "")).lower()
            secret_key = getattr(settings, "secret_key", "")
            if Bootloader._is_protected_runtime(environment):
                if not isinstance(secret_key, str) or not secret_key.strip():
                    logger.error("SECRET_KEY is required in protected environments", environment=environment)
                    return False
                normalized_secret = secret_key.strip()
                if normalized_secret == DEVELOPMENT_SECRET_KEY:
                    logger.error("Default development SECRET_KEY is forbidden", environment=environment)
                    return False
                if len(normalized_secret.encode("utf-8")) < 32:
                    logger.error("SECRET_KEY must be at least 32 bytes", environment=environment)
                    return False
                if str(database_url).strip() == DEVELOPMENT_DATABASE_URL:
                    logger.error("Default development DATABASE_URL is forbidden", environment=environment)
                    return False
                if str(getattr(settings, "s3_secret_key", "")).strip() == DEVELOPMENT_S3_SECRET_KEY:
                    logger.error("Default development S3_SECRET_KEY is forbidden", environment=environment)
                    return False
            return True
        except Exception as e:
            logger.error("Configuration load failed", error=str(e))
            return False

    @staticmethod
    async def _check_database() -> ServiceStatus:
        """Verify database connectivity (SELECT 1)."""
        start = time.perf_counter()
        engine = None
        try:
            engine = create_async_engine(settings.database_url, echo=False)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

            duration_ms = (time.perf_counter() - start) * 1000
            return ServiceStatus("database", "ok", "Connection successful", duration_ms)

        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return ServiceStatus("database", "error", str(e), duration_ms)
        finally:
            if engine:
                await engine.dispose()

    @staticmethod
    async def _check_s3() -> ServiceStatus:
        """HEAD bucket check."""
        import aioboto3
        from botocore.config import Config

        start = time.perf_counter()
        try:
            session = aioboto3.Session()
            async with session.client(
                "s3",
                endpoint_url=settings.s3_endpoint,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key,
                region_name=settings.s3_region,
                config=Config(connect_timeout=5, read_timeout=5),
            ) as s3:
                await s3.head_bucket(Bucket=settings.s3_bucket)

            duration_ms = (time.perf_counter() - start) * 1000
            return ServiceStatus("minio", "ok", "Bucket accessible", duration_ms)
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return ServiceStatus("minio", "error", str(e), duration_ms)

    @staticmethod
    async def _check_ai_provider() -> ServiceStatus:
        """Report the configured AI provider (the model catalogue is local — see
        ``src/llm/catalog.py`` — so there is no remote ``/models`` probe)."""
        api_key = getattr(settings, "ai_api_key", None)
        if not isinstance(api_key, str) or not api_key:
            return ServiceStatus("ai_provider", "skipped", "Not configured")

        return ServiceStatus(
            "ai_provider",
            "ok",
            f"Configured provider={settings.ai_provider}, primary={settings.primary_model}, ocr={settings.ocr_model}",
        )

    _check_openrouter = _check_ai_provider

    @staticmethod
    def _check_vault_secrets() -> ServiceStatus:
        """Check if Vault secrets file exists and is fresh (staging/production only)."""
        start = time.perf_counter()

        if not os.path.exists(VAULT_SECRETS_FILE_PATH):
            duration_ms = (time.perf_counter() - start) * 1000
            return ServiceStatus(
                "vault_secrets",
                "warning",
                f"Secrets file not found at {VAULT_SECRETS_FILE_PATH}. "
                "If in staging/production, check if Vault token has expired. "
                "Run: invoke vault.setup-tokens --project=finance_report",
                duration_ms,
            )

        try:
            stat = os.stat(VAULT_SECRETS_FILE_PATH)
            file_age_seconds = time.time() - stat.st_mtime

            if file_age_seconds > VAULT_SECRETS_STALENESS_THRESHOLD_SECONDS:
                duration_ms = (time.perf_counter() - start) * 1000
                return ServiceStatus(
                    "vault_secrets",
                    "warning",
                    f"Secrets file is {int(file_age_seconds / 3600)}h old. "
                    "Vault-agent may have stopped refreshing. Check token expiry.",
                    duration_ms,
                )

            duration_ms = (time.perf_counter() - start) * 1000
            return ServiceStatus(
                "vault_secrets",
                "ok",
                f"Secrets file exists, last modified {int(file_age_seconds)}s ago",
                duration_ms,
            )

        except OSError as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return ServiceStatus("vault_secrets", "error", str(e), duration_ms)


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

    if success:
        print("✅ Validation check passed.")
        sys.exit(0)
    else:
        print("❌ Validation check failed.")
        sys.exit(1)
