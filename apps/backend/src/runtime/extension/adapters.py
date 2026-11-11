"""`DependencyCheck` adapters — concrete presence probes."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse

from infra2_sdk.runtime import (
    HttpClientSettings,
    PostgresSettings,
    probe_http,
    probe_orchestrator,
    redact_postgres_error,
)
from infra2_sdk.runtime.health import DependencyStatus, ProbeResult
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

_HTTP_5S = HttpClientSettings(timeout_seconds=5.0, connect_timeout_seconds=5.0)


def _ok(name: str, detail: str, start: float) -> ProbeResult:
    return ProbeResult(name, DependencyStatus.PRESENT, detail, (time.perf_counter() - start) * 1000)


def _absent(name: str, detail: str = "Not configured", start: float | None = None) -> ProbeResult:
    elapsed = 0.0 if start is None else (time.perf_counter() - start) * 1000
    return ProbeResult(name, DependencyStatus.ABSENT, detail, elapsed)


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
            return _ok(self.name, "Connection successful", start)
        except Exception as exc:  # noqa: BLE001
            detail = str(exc)
            try:
                detail = redact_postgres_error(detail, PostgresSettings(dsn=self._database_url))
            except Exception:  # noqa: BLE001
                pass
            return _absent(self.name, detail, start)
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
            async with aioboto3.Session().client(
                "s3",
                endpoint_url=self._endpoint,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                region_name=self._region,
                config=Config(connect_timeout=5, read_timeout=5),
            ) as s3:
                await s3.head_bucket(Bucket=self._bucket)
            return _ok(self.name, "Bucket accessible", start)
        except Exception as exc:  # noqa: BLE001
            return _absent(self.name, str(exc), start)


class LlmCheck:
    """AI provider configuration presence."""

    name = "llm"

    def __init__(
        self,
        *,
        api_key: str | None,
        provider: str,
        small_model: str,
        multimodal_model: str,
    ) -> None:
        self._api_key = api_key
        self._provider = provider
        self._small_model = small_model
        self._multimodal_model = multimodal_model

    async def probe(self) -> ProbeResult:
        start = time.perf_counter()
        if not isinstance(self._api_key, str) or not self._api_key:
            return _absent(self.name, "Not configured", start)
        detail = f"Configured provider={self._provider}, small={self._small_model}, multimodal={self._multimodal_model}"
        return _ok(self.name, detail, start)


class RedisCheck:
    """Redis reachability via a raw TCP ``PING``."""

    name = "cache"

    def __init__(self, *, url: str | None) -> None:
        self._url = url

    async def probe(self) -> ProbeResult:
        if not self._url:
            return _absent(self.name)
        start = time.perf_counter()
        try:
            parsed = urlparse(self._url)
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(parsed.hostname, parsed.port or 6379), timeout=5
            )
            try:
                writer.write(b"PING\r\n")
                await writer.drain()
                reply = await asyncio.wait_for(reader.readline(), timeout=5)
            finally:
                writer.close()
                await writer.wait_closed()
            if reply.startswith((b"+PONG", b"-NOAUTH", b"-ERR")):
                return _ok(self.name, "PING answered", start)
            return _absent(self.name, f"Unexpected reply {reply[:20]!r}", start)
        except Exception as exc:  # noqa: BLE001
            return _absent(self.name, str(exc), start)


class WorkflowEngineCheck:
    """Prefect API reachability via ``GET {api_url}/health``."""

    name = "workflow_engine"

    def __init__(self, *, api_url: str | None) -> None:
        self._api_url = api_url

    async def probe(self) -> ProbeResult:
        if not self._api_url:
            return _absent(self.name)
        return await probe_orchestrator(f"{self._api_url.rstrip('/')}/health", name=self.name, settings=_HTTP_5S)


class TelemetryCheck:
    """OTLP collector reachability via TCP connect."""

    name = "telemetry"

    def __init__(self, *, endpoint: str | None) -> None:
        self._endpoint = endpoint

    async def probe(self) -> ProbeResult:
        if not self._endpoint:
            return _absent(self.name)
        start = time.perf_counter()
        try:
            parsed = urlparse(self._endpoint if "//" in self._endpoint else f"//{self._endpoint}")
            port = parsed.port or (443 if parsed.scheme == "https" else 4317)
            _reader, writer = await asyncio.wait_for(asyncio.open_connection(parsed.hostname, port), timeout=5)
            writer.close()
            await writer.wait_closed()
            return _ok(self.name, "Collector reachable", start)
        except Exception as exc:  # noqa: BLE001
            return _absent(self.name, str(exc), start)


class AnalyticsCheck:
    """OpenPanel API reachability."""

    name = "analytics"

    def __init__(self, *, api_url: str | None) -> None:
        self._api_url = api_url

    async def probe(self) -> ProbeResult:
        if not self._api_url:
            return _absent(self.name)
        return await probe_http(self._api_url, name=self.name, settings=_HTTP_5S)


class MarketDataCheck:
    """Yahoo Finance reachability."""

    name = "market_data"
    _PROBE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X"

    def __init__(self, *, timeout_seconds: int) -> None:
        self._timeout_seconds = timeout_seconds

    async def probe(self) -> ProbeResult:
        settings = HttpClientSettings(
            timeout_seconds=float(self._timeout_seconds),
            connect_timeout_seconds=float(self._timeout_seconds),
            user_agent="finance-report-smoke/1.0",
        )
        return await probe_http(self._PROBE_URL, name=self.name, settings=settings)
