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

from src.config import settings
from src.logger import get_logger

logger = get_logger(__name__)


class BootMode(str, Enum):
    CRITICAL = "critical"  # DB only (Fast fail for startup)
    FULL = "full"  # DB + Redis + S3 + AI (Smoke tests)
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
        logger.info(f"Bootloader starting validation", mode=mode.value)
        
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
            results.append(await Bootloader._check_redis())
            results.append(await Bootloader._check_s3())
            results.append(await Bootloader._check_openrouter())

        # 3. Report Results
        passed = True
        for res in results:
            if res.status == "error":
                passed = False
                logger.error(
                    f"Service check failed",
                    service=res.service,
                    error=res.message,
                    duration_ms=res.duration_ms
                )
            elif res.status == "warning":
                logger.warning(
                    f"Service check warning",
                    service=res.service,
                    message=res.message,
                    duration_ms=res.duration_ms
                )
            else:
                logger.info(
                    f"Service check passed",
                    service=res.service,
                    duration_ms=res.duration_ms
                )

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
            "primary_model",
            "s3_endpoint",
            "s3_bucket",
            "cors_origin_regex",
            "otel_exporter_otlp_endpoint",
            "otel_service_name",
        ]

        # Sensitive fields - only show "set"/"not set" status
        sensitive_fields = [
            "database_url",
            "redis_url",
            "openrouter_api_key",
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
    def _check_static_config() -> bool:
        """Verify presence of required environment variables."""
        try:
            # Just accessing settings triggers validation
            _ = settings.database_url
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
    async def _check_redis() -> ServiceStatus:
        if not settings.redis_url:
            return ServiceStatus("redis", "skipped", "Not configured")
            
        start = time.perf_counter()
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(settings.redis_url, decode_responses=True)
            await client.ping()
            await client.aclose()
            duration_ms = (time.perf_counter() - start) * 1000
            return ServiceStatus("redis", "ok", "Ping successful", duration_ms)
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return ServiceStatus("redis", "error", str(e), duration_ms)

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
    async def _check_openrouter() -> ServiceStatus:
        """Validate AI API key."""
        if not settings.openrouter_api_key:
            return ServiceStatus("openrouter", "skipped", "Not configured")

        import httpx
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{settings.openrouter_base_url}/models",
                    headers={"Authorization": f"Bearer {settings.openrouter_api_key}"}
                )
                if resp.status_code == 200:
                    status = "ok"
                    msg = "API Key valid"
                else:
                    status = "error"
                    msg = f"HTTP {resp.status_code}"
            
            duration_ms = (time.perf_counter() - start) * 1000
            return ServiceStatus("openrouter", status, msg, duration_ms)
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return ServiceStatus("openrouter", "error", str(e), duration_ms)


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
