"""Environment variable smoke test - validates actual connectivity.

This module performs functional tests on configured services to verify
that environment variables not only exist but actually work.

Tests include:
- Database: Connect and query
- MinIO/S3: Upload, download, delete test object
- Redis: Set, get, delete test key
- OpenRouter: Validate API key (optional ping)

Usage:
    python -m src.env_smoke_test
    python -m src.env_smoke_test --quick  # Skip optional services
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.config import settings
from src.logger import get_logger
from src.services.storage import StorageService

logger = get_logger(__name__)


@dataclass
class TestResult:
    """Result of a smoke test."""

    service: str
    status: str  # 'ok', 'warning', 'error', 'skipped'
    message: str
    duration_ms: float = 0.0
    details: dict[str, Any] | None = None


class EnvironmentSmokeTest:
    """Functional smoke tests for environment configuration."""

    def __init__(self, skip_optional: bool = False):
        self.skip_optional = skip_optional
        self.results: list[TestResult] = []

    async def test_database(self) -> TestResult:
        """Test database connectivity and basic operations."""
        logger.info(
            "Starting database smoke test",
            database_url_prefix=settings.database_url.split("@")[0]
            if "@" in settings.database_url
            else "***",
        )
        start = time.perf_counter()
        engine = None
        try:
            engine = create_async_engine(settings.database_url, echo=False)
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT 1 as test"))
                row = result.fetchone()
                if not (row is not None and row[0] == 1):
                    raise ValueError("SELECT 1 validation failed")

                test_table = f"smoke_test_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
                await conn.execute(
                    text(
                        f"""
                    CREATE TEMPORARY TABLE {test_table} (
                        id SERIAL PRIMARY KEY,
                        test_data TEXT
                    )
                """
                    )
                )

                await conn.execute(
                    text(f"INSERT INTO {test_table} (test_data) VALUES (:data)"),
                    {"data": "smoke_test"},
                )

                result = await conn.execute(text(f"SELECT test_data FROM {test_table}"))
                row = result.fetchone()
                if not (row is not None and row[0] == "smoke_test"):
                    row_value = row[0] if row else None
                    raise ValueError(
                        f"Insert/Select validation failed: expected 'smoke_test', got {row_value!r}"
                    )

            duration_ms = (time.perf_counter() - start) * 1000
            return TestResult(
                service="database",
                status="ok",
                message="Connection, create table, insert, select all OK",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "Database smoke test failed",
                error=str(exc),
                error_type=type(exc).__name__,
                database_url_prefix=settings.database_url.split("@")[0]
                if "@" in settings.database_url
                else "***",
            )
            return TestResult(
                service="database",
                status="error",
                message=f"Database test failed: {exc}",
                duration_ms=duration_ms,
            )
        finally:
            if engine is not None:
                await engine.dispose()

    async def test_redis(self) -> TestResult:
        """Test Redis connectivity and basic operations."""
        if not settings.redis_url:
            return TestResult(
                service="redis",
                status="skipped" if self.skip_optional else "warning",
                message="REDIS_URL not configured (optional for local dev)",
                duration_ms=0.0,
            )

        logger.info(
            "Starting Redis smoke test",
            redis_url_prefix=settings.redis_url.split("@")[0]
            if "@" in settings.redis_url
            else "***",
        )
        start = time.perf_counter()
        redis = None

        try:
            import redis.asyncio as aioredis

            redis = aioredis.from_url(settings.redis_url, decode_responses=True)

            await redis.ping()

            test_key = f"smoke_test:{datetime.now(UTC).isoformat()}"
            test_value = "smoke_test_value"

            await redis.set(test_key, test_value, ex=10)
            retrieved = await redis.get(test_key)
            if retrieved != test_value:
                raise ValueError(
                    f"Set/Get validation failed: expected {test_value!r}, got {retrieved!r}"
                )

            await redis.delete(test_key)
            deleted = await redis.get(test_key)
            if deleted is not None:
                raise ValueError(f"Delete validation failed: expected None, got {deleted!r}")

            duration_ms = (time.perf_counter() - start) * 1000
            return TestResult(
                service="redis",
                status="ok",
                message="Ping, set, get, delete all OK",
                duration_ms=duration_ms,
            )
        except ImportError:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.warning("Redis package not installed")
            return TestResult(
                service="redis",
                status="skipped",
                message="redis package not installed",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "Redis smoke test failed",
                error=str(exc),
                error_type=type(exc).__name__,
                redis_url_prefix=settings.redis_url.split("@")[0]
                if "@" in settings.redis_url
                else "***",
            )
            return TestResult(
                service="redis",
                status="error",
                message=f"Redis test failed: {exc}",
                duration_ms=duration_ms,
            )
        finally:
            if redis is not None:
                await redis.aclose()

    async def test_minio(self) -> TestResult:
        """Test MinIO/S3 connectivity and basic operations."""
        logger.info(
            "Starting MinIO smoke test",
            s3_endpoint=settings.s3_endpoint,
            s3_bucket=settings.s3_bucket,
        )
        start = time.perf_counter()
        test_key = None
        storage = None

        try:
            storage = StorageService()
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
            test_key = f"smoke_test/{timestamp}.txt"
            test_content = f"Smoke test at {datetime.now(UTC).isoformat()}".encode()

            loop = asyncio.get_running_loop()

            await loop.run_in_executor(
                None,
                lambda: storage.upload_bytes(
                    key=test_key, content=test_content, content_type="text/plain"
                ),
            )

            downloaded = await loop.run_in_executor(None, storage.get_object, test_key)
            if downloaded != test_content:
                raise ValueError("Upload/Download content mismatch")

            presigned_url = await loop.run_in_executor(
                None, lambda: storage.generate_presigned_url(key=test_key, public=False)
            )
            if not presigned_url.startswith("http"):
                raise ValueError(f"Invalid presigned URL: {presigned_url}")

            duration_ms = (time.perf_counter() - start) * 1000

            try:
                await loop.run_in_executor(None, storage.delete_object, test_key)
                cleanup_warning = None
            except Exception as cleanup_exc:
                cleanup_warning = f"Cleanup failed: {cleanup_exc}"
                logger.warning(
                    "MinIO smoke test cleanup failed",
                    test_key=test_key,
                    error=str(cleanup_exc),
                )

            return TestResult(
                service="minio",
                status="ok",
                message=(
                    "Upload, download, presigned URL, delete all OK"
                    if not cleanup_warning
                    else f"Tests passed but cleanup warning: {cleanup_warning}"
                ),
                duration_ms=duration_ms,
                details={
                    "test_key": test_key,
                    "content_size": len(test_content),
                    "cleanup_warning": cleanup_warning,
                },
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "MinIO smoke test failed",
                error=str(exc),
                error_type=type(exc).__name__,
                test_key=test_key,
                s3_endpoint=settings.s3_endpoint,
                s3_bucket=settings.s3_bucket,
            )

            if test_key and storage:
                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, storage.delete_object, test_key)
                except Exception as cleanup_exc:
                    logger.warning(
                        "Failed to cleanup test file after error",
                        test_key=test_key,
                        error=str(cleanup_exc),
                    )

            return TestResult(
                service="minio",
                status="error",
                message=f"MinIO test failed: {exc}",
                duration_ms=duration_ms,
            )

    async def test_openrouter(self) -> TestResult:
        """Test OpenRouter API key validity."""
        if not settings.openrouter_api_key:
            return TestResult(
                service="openrouter",
                status="skipped" if self.skip_optional else "warning",
                message="OPENROUTER_API_KEY not configured (AI features disabled)",
                duration_ms=0.0,
            )

        logger.info("Starting OpenRouter smoke test")
        start = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{settings.openrouter_base_url}/models",
                    headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                )

                if response.status_code == 200:
                    models = response.json().get("data", [])
                    primary_available = any(m.get("id") == settings.primary_model for m in models)
                    duration_ms = (time.perf_counter() - start) * 1000
                    return TestResult(
                        service="openrouter",
                        status="ok",
                        message=f"API key valid, {len(models)} models available",
                        duration_ms=duration_ms,
                        details={
                            "primary_model": settings.primary_model,
                            "primary_available": primary_available,
                        },
                    )
                elif response.status_code == 401:
                    duration_ms = (time.perf_counter() - start) * 1000
                    logger.warning("OpenRouter API key invalid (401 Unauthorized)")
                    return TestResult(
                        service="openrouter",
                        status="error",
                        message="API key invalid (401 Unauthorized)",
                        duration_ms=duration_ms,
                    )
                else:
                    duration_ms = (time.perf_counter() - start) * 1000
                    logger.warning(
                        "Unexpected OpenRouter response",
                        status_code=response.status_code,
                    )
                    return TestResult(
                        service="openrouter",
                        status="warning",
                        message=f"Unexpected response: {response.status_code}",
                        duration_ms=duration_ms,
                    )
        except httpx.TimeoutException as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.warning("OpenRouter API request timed out", timeout_seconds=10.0)
            return TestResult(
                service="openrouter",
                status="error",
                message=f"Request timed out after 10 seconds: {exc}",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "OpenRouter smoke test failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return TestResult(
                service="openrouter",
                status="error",
                message=f"OpenRouter test failed: {exc}",
                duration_ms=duration_ms,
            )

    async def run_all_tests(self) -> list[TestResult]:
        """Run all smoke tests in parallel where possible."""
        logger.info("Starting environment smoke tests")

        db_result = await self.test_database()
        self.results.append(db_result)

        tasks = [
            self.test_redis(),
            self.test_minio(),
            self.test_openrouter(),
        ]
        other_results = await asyncio.gather(*tasks, return_exceptions=False)
        self.results.extend(other_results)

        return self.results

    def print_results(self) -> None:
        """Print formatted test results."""
        print("\n" + "=" * 80)
        print("Environment Smoke Test Results")
        print("=" * 80)

        status_symbols = {
            "ok": "✅",
            "warning": "⚠️",
            "error": "❌",
            "skipped": "⏭️",
        }

        for result in self.results:
            symbol = status_symbols.get(result.status, "?")
            duration = f"({result.duration_ms:.0f}ms)" if result.duration_ms > 0 else ""
            print(f"\n{symbol} {result.service.upper()} {duration}")
            print(f"   {result.message}")
            if result.details:
                for key, value in result.details.items():
                    print(f"   - {key}: {value}")

        print("\n" + "=" * 80)

        ok_count = sum(1 for r in self.results if r.status == "ok")
        warning_count = sum(1 for r in self.results if r.status == "warning")
        error_count = sum(1 for r in self.results if r.status == "error")
        skipped_count = sum(1 for r in self.results if r.status == "skipped")

        print(
            f"\nSummary: {ok_count} OK, {warning_count} warnings, "
            f"{error_count} errors, {skipped_count} skipped"
        )

        if error_count > 0:
            print("\n⚠️  Critical services failed - application may not function correctly")
        elif warning_count > 0:
            print("\n⚠️  Some optional services unavailable - features may be degraded")
        else:
            print("\n✅ All configured services are healthy")

        print("=" * 80 + "\n")

    def has_errors(self) -> bool:
        """Check if any test failed."""
        return any(r.status == "error" for r in self.results)


async def main() -> None:
    """Run smoke tests and exit with appropriate code."""
    parser = argparse.ArgumentParser(description="Environment smoke test")
    parser.add_argument(
        "--quick", action="store_true", help="Skip optional service tests (Redis, OpenRouter)"
    )
    parser.add_argument(
        "--critical-only",
        action="store_true",
        help="Test only critical services (DB + S3) for fast container startup validation",
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Exit with error code if warnings found",
    )
    args = parser.parse_args()

    skip_optional = args.quick or args.critical_only

    tester = EnvironmentSmokeTest(skip_optional=skip_optional)

    if args.critical_only:
        results = []
        results.append(await tester.test_database())
        results.append(await tester.test_minio())
        tester.results = results
    else:
        await tester.run_all_tests()

    tester.print_results()

    if tester.has_errors():
        sys.exit(1)
    elif args.fail_on_warning and any(r.status == "warning" for r in tester.results):
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
