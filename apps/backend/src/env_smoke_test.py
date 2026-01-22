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

import asyncio
import hashlib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
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
        start = asyncio.get_event_loop().time()
        try:
            engine = create_async_engine(settings.database_url, echo=False)
            async with engine.connect() as conn:
                # 1. Test connection
                result = await conn.execute(text("SELECT 1 as test"))
                row = result.fetchone()
                assert row is not None and row[0] == 1, "SELECT 1 failed"

                # 2. Test table creation (in transaction, auto rollback)
                test_table = f"smoke_test_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
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

                # 3. Test insert
                await conn.execute(
                    text(f"INSERT INTO {test_table} (test_data) VALUES (:data)"),
                    {"data": "smoke_test"},
                )

                # 4. Test select
                result = await conn.execute(text(f"SELECT test_data FROM {test_table}"))
                row = result.fetchone()
                assert row is not None and row[0] == "smoke_test", "Insert/Select failed"

            await engine.dispose()
            duration_ms = (asyncio.get_event_loop().time() - start) * 1000
            return TestResult(
                service="database",
                status="ok",
                message="Connection, create table, insert, select all OK",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (asyncio.get_event_loop().time() - start) * 1000
            return TestResult(
                service="database",
                status="error",
                message=f"Database test failed: {exc}",
                duration_ms=duration_ms,
            )

    async def test_redis(self) -> TestResult:
        """Test Redis connectivity and basic operations."""
        start = asyncio.get_event_loop().time()

        if not settings.redis_url:
            return TestResult(
                service="redis",
                status="skipped" if self.skip_optional else "warning",
                message="REDIS_URL not configured (optional for local dev)",
                duration_ms=0.0,
            )

        try:
            import redis.asyncio as aioredis

            redis = aioredis.from_url(settings.redis_url, decode_responses=True)

            # 1. Test connection
            await redis.ping()

            # 2. Test set/get/delete
            test_key = f"smoke_test:{datetime.now(timezone.utc).isoformat()}"
            test_value = "smoke_test_value"

            await redis.set(test_key, test_value, ex=10)
            retrieved = await redis.get(test_key)
            assert retrieved == test_value, "Set/Get failed"

            await redis.delete(test_key)
            deleted = await redis.get(test_key)
            assert deleted is None, "Delete failed"

            await redis.aclose()
            duration_ms = (asyncio.get_event_loop().time() - start) * 1000
            return TestResult(
                service="redis",
                status="ok",
                message="Ping, set, get, delete all OK",
                duration_ms=duration_ms,
            )
        except ImportError:
            duration_ms = (asyncio.get_event_loop().time() - start) * 1000
            return TestResult(
                service="redis",
                status="skipped",
                message="redis package not installed",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (asyncio.get_event_loop().time() - start) * 1000
            return TestResult(
                service="redis",
                status="error",
                message=f"Redis test failed: {exc}",
                duration_ms=duration_ms,
            )

    async def test_minio(self) -> TestResult:
        """Test MinIO/S3 connectivity and basic operations."""
        start = asyncio.get_event_loop().time()
        try:
            storage = StorageService()
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            test_key = f"smoke_test/{timestamp}.txt"
            test_content = f"Smoke test at {datetime.now(timezone.utc).isoformat()}".encode()

            # Run in thread pool since storage service is synchronous
            loop = asyncio.get_event_loop()

            # 1. Test upload
            await loop.run_in_executor(
                None,
                lambda: storage.upload_bytes(
                    key=test_key, content=test_content, content_type="text/plain"
                ),
            )

            # 2. Test download
            downloaded = await loop.run_in_executor(None, storage.get_object, test_key)
            assert downloaded == test_content, "Upload/Download content mismatch"

            # 3. Test presigned URL generation (internal endpoint)
            presigned_url = await loop.run_in_executor(
                None, lambda: storage.generate_presigned_url(key=test_key, public=False)
            )
            assert presigned_url.startswith("http"), "Invalid presigned URL"

            # 4. Test delete
            await loop.run_in_executor(None, storage.delete_object, test_key)

            duration_ms = (asyncio.get_event_loop().time() - start) * 1000
            return TestResult(
                service="minio",
                status="ok",
                message="Upload, download, presigned URL, delete all OK",
                duration_ms=duration_ms,
                details={"test_key": test_key, "content_size": len(test_content)},
            )
        except Exception as exc:
            duration_ms = (asyncio.get_event_loop().time() - start) * 1000
            return TestResult(
                service="minio",
                status="error",
                message=f"MinIO test failed: {exc}",
                duration_ms=duration_ms,
            )

    async def test_openrouter(self) -> TestResult:
        """Test OpenRouter API key validity."""
        start = asyncio.get_event_loop().time()

        if not settings.openrouter_api_key:
            return TestResult(
                service="openrouter",
                status="skipped" if self.skip_optional else "warning",
                message="OPENROUTER_API_KEY not configured (AI features disabled)",
                duration_ms=0.0,
            )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{settings.openrouter_base_url}/models",
                    headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                )

                if response.status_code == 200:
                    models = response.json().get("data", [])
                    primary_available = any(m.get("id") == settings.primary_model for m in models)
                    duration_ms = (asyncio.get_event_loop().time() - start) * 1000
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
                    duration_ms = (asyncio.get_event_loop().time() - start) * 1000
                    return TestResult(
                        service="openrouter",
                        status="error",
                        message="API key invalid (401 Unauthorized)",
                        duration_ms=duration_ms,
                    )
                else:
                    duration_ms = (asyncio.get_event_loop().time() - start) * 1000
                    return TestResult(
                        service="openrouter",
                        status="warning",
                        message=f"Unexpected response: {response.status_code}",
                        duration_ms=duration_ms,
                    )
        except Exception as exc:
            duration_ms = (asyncio.get_event_loop().time() - start) * 1000
            return TestResult(
                service="openrouter",
                status="error",
                message=f"OpenRouter test failed: {exc}",
                duration_ms=duration_ms,
            )

    async def run_all_tests(self) -> list[TestResult]:
        """Run all smoke tests in parallel where possible."""
        logger.info("Starting environment smoke tests")

        # Database test must run first (may create schemas)
        db_result = await self.test_database()
        self.results.append(db_result)

        # Run other tests in parallel
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

        # Summary
        ok_count = sum(1 for r in self.results if r.status == "ok")
        warning_count = sum(1 for r in self.results if r.status == "warning")
        error_count = sum(1 for r in self.results if r.status == "error")
        skipped_count = sum(1 for r in self.results if r.status == "skipped")

        print(
            f"\nSummary: {ok_count} OK, {warning_count} warnings, {error_count} errors, {skipped_count} skipped"
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
    import argparse

    parser = argparse.ArgumentParser(description="Environment smoke test")
    parser.add_argument(
        "--quick", action="store_true", help="Skip optional service tests (Redis, OpenRouter)"
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Exit with error code if warnings found",
    )
    args = parser.parse_args()

    tester = EnvironmentSmokeTest(skip_optional=args.quick)
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
