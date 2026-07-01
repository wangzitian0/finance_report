"""`DependencyCheck` adapters — the concrete presence probes.

These own the reachability logic (relocated from `apps/backend/src/boot.py`'s
`_check_*`); `boot.Bootloader` now delegates to them. Config values are injected
via the constructor (the adapters never reach a global `settings`), so the
package stays a pure `kernel` leaf. Each returns a `ProbeResult` (binary status +
detail + timing); probes never raise for an ordinary outage — an unreachable
backend is `ABSENT`.
"""

from __future__ import annotations

import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.runtime.base.check import DependencyStatus, ProbeResult


class DatabaseCheck:
    """Postgres reachability via `SELECT 1`."""

    name = "database"

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def probe(self) -> ProbeResult:
        start = time.perf_counter()
        engine = None
        try:
            engine = create_async_engine(self._database_url, echo=False)
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return ProbeResult(
                self.name,
                DependencyStatus.PRESENT,
                "Connection successful",
                (time.perf_counter() - start) * 1000,
            )
        except Exception as exc:  # noqa: BLE001 - any failure means ABSENT
            return ProbeResult(
                self.name,
                DependencyStatus.ABSENT,
                str(exc),
                (time.perf_counter() - start) * 1000,
            )
        finally:
            if engine is not None:
                await engine.dispose()


class ObjectStorageCheck:
    """S3-compatible object storage reachability via `head_bucket`."""

    name = "object_storage"

    def __init__(
        self,
        *,
        endpoint: str | None,
        access_key: str | None,
        secret_key: str | None,
        region: str | None,
        bucket: str,
    ) -> None:
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region
        self._bucket = bucket

    async def probe(self) -> ProbeResult:
        import aioboto3
        from botocore.config import Config

        start = time.perf_counter()
        try:
            session = aioboto3.Session()
            async with session.client(
                "s3",
                endpoint_url=self._endpoint,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                region_name=self._region,
                config=Config(connect_timeout=5, read_timeout=5),
            ) as s3:
                await s3.head_bucket(Bucket=self._bucket)
            return ProbeResult(
                self.name,
                DependencyStatus.PRESENT,
                "Bucket accessible",
                (time.perf_counter() - start) * 1000,
            )
        except Exception as exc:  # noqa: BLE001 - any failure means ABSENT
            return ProbeResult(
                self.name,
                DependencyStatus.ABSENT,
                str(exc),
                (time.perf_counter() - start) * 1000,
            )


class LlmCheck:
    """AI provider configuration presence.

    The model catalogue is local (`src/llm/catalog.py`), so there is no remote
    probe: the dependency is PRESENT iff an API key is configured.
    """

    name = "llm"

    def __init__(
        self,
        *,
        api_key: str | None,
        provider: str,
        primary_model: str,
        ocr_model: str,
    ) -> None:
        self._api_key = api_key
        self._provider = provider
        self._primary_model = primary_model
        self._ocr_model = ocr_model

    async def probe(self) -> ProbeResult:
        start = time.perf_counter()
        if not isinstance(self._api_key, str) or not self._api_key:
            return ProbeResult(
                self.name,
                DependencyStatus.ABSENT,
                "Not configured",
                (time.perf_counter() - start) * 1000,
            )
        return ProbeResult(
            self.name,
            DependencyStatus.PRESENT,
            f"Configured provider={self._provider}, primary={self._primary_model}, ocr={self._ocr_model}",
            (time.perf_counter() - start) * 1000,
        )
