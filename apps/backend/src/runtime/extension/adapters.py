"""`DependencyCheck` adapters — concrete presence probes."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from infra2_sdk.runtime import (
    HttpClientSettings,
    PostgresSettings,
    S3Settings,
    probe_http,
    probe_orchestrator,
    probe_s3,
    redact_postgres_error,
    s3 as sdk_s3,
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
            engine = create_async_engine(self._database_url, echo=False, hide_parameters=True)
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


def _redact_secret(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret else text


def _probe_s3_write_delete(s3_settings: S3Settings) -> None:
    """Write a small health object and always delete it, closing the S3 client afterwards."""
    client = sdk_s3.create_s3_client(s3_settings)
    key = f"_health_probe/{uuid4().hex}.txt"
    put_error: Exception | None = None
    try:
        client.put_object(Bucket=s3_settings.bucket, Key=key, Body=b"ok")
    except Exception as exc:  # noqa: BLE001
        put_error = exc
        raise
    finally:
        delete_error: Exception | None = None
        try:
            client.delete_object(Bucket=s3_settings.bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            delete_error = exc
        finally:
            if hasattr(client, "close"):
                with contextlib.suppress(Exception):
                    client.close()
        if put_error is None and delete_error is not None:
            raise delete_error


class ObjectStorageCheck:
    """S3-compatible object storage reachability via `head_bucket` and optional write/delete probe."""

    name = "object_storage"

    def __init__(
        self,
        *,
        endpoint: str | None,
        access_key: str | None,
        secret_key: str | None,
        region: str | None,
        bucket: str,
        public_endpoint: str | None = None,
        public_access_key: str | None = None,
        public_secret_key: str | None = None,
        public_bucket: str | None = None,
        verify_write: bool = False,
    ) -> None:
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region
        self._bucket = bucket
        self._public_endpoint = public_endpoint
        self._public_access_key = public_access_key
        self._public_secret_key = public_secret_key
        self._public_bucket = public_bucket
        self._verify_write = verify_write

    async def probe(self) -> ProbeResult:
        start = time.perf_counter()
        try:
            primary = S3Settings(
                bucket=self._bucket,
                endpoint_url=self._endpoint,
                access_key_id=self._access_key,
                secret_access_key=self._secret_key,
                region_name=self._region,
            )
            primary_res = await asyncio.to_thread(probe_s3, primary)
        except Exception as exc:  # noqa: BLE001
            return _absent(self.name, str(exc), start)

        if primary_res.status is not DependencyStatus.PRESENT:
            return primary_res

        parts = ["bucket accessible"]
        public_ep = self._public_endpoint.strip() if isinstance(self._public_endpoint, str) else ""
        if public_ep:
            try:
                public = S3Settings(
                    bucket=(self._public_bucket or "").strip() or self._bucket,
                    endpoint_url=public_ep,
                    access_key_id=(self._public_access_key or "").strip() or self._access_key,
                    secret_access_key=(self._public_secret_key or "").strip() or self._secret_key,
                    region_name=self._region,
                )
                pub_res = await asyncio.to_thread(probe_s3, public)
            except Exception as exc:  # noqa: BLE001
                return _absent(self.name, f"public S3 probe failed: {type(exc).__name__}: {exc}", start)
            if pub_res.status is not DependencyStatus.PRESENT:
                return _absent(self.name, f"public S3 probe failed: {pub_res.detail}", start)
            parts.append("public endpoint accessible")

        if self._verify_write:
            try:
                await asyncio.to_thread(_probe_s3_write_delete, primary)
            except Exception as exc:  # noqa: BLE001
                return _absent(self.name, f"S3 write/delete probe failed: {type(exc).__name__}: {exc}", start)
            parts.append("write/delete ok")

        if not public_ep and not self._verify_write:
            return primary_res
        return _ok(self.name, ", ".join(parts), start)


class LlmCheck:
    """AI provider reachability and authentication probe."""

    name = "llm"

    def __init__(
        self,
        *,
        api_key: str | None,
        provider: str,
        small_model: str,
        multimodal_model: str,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._provider = provider
        self._small_model = small_model
        self._multimodal_model = multimodal_model
        self._base_url = base_url

    async def probe(self) -> ProbeResult:
        start = time.perf_counter()
        key = self._api_key.strip() if isinstance(self._api_key, str) else ""
        if not key:
            return _absent(self.name, "Not configured", start)
        base = self._base_url.strip().rstrip("/") if isinstance(self._base_url, str) else ""
        if not base:
            return _absent(self.name, "Missing LLM base_url", start)

        headers = {"Authorization": f"Bearer {key}"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{base}/models", headers=headers)
                code = int(resp.status_code)
                if 200 <= code < 300 or code == 429:
                    return _ok(self.name, f"provider={self._provider} models={code}", start)
                if code in {401, 403}:
                    return _absent(self.name, f"Authentication failed (HTTP {code})", start)
                if code in {404, 405}:
                    chat_resp = await client.post(f"{base}/chat/completions", headers=headers, json={})
                    chat_code = int(chat_resp.status_code)
                    if chat_code in {200, 400, 422, 429}:
                        return _ok(self.name, f"provider={self._provider} chat_probe={chat_code}", start)
                    return _absent(self.name, f"LLM endpoint HTTP {chat_code}", start)
                return _absent(self.name, f"LLM endpoint HTTP {code}", start)
        except Exception as exc:  # noqa: BLE001
            return _absent(self.name, _redact_secret(f"{type(exc).__name__}: {exc}", key), start)


class RedisCheck:
    """Redis reachability via authenticated ``redis.asyncio`` ``PING``."""

    name = "cache"

    def __init__(self, *, url: str | None) -> None:
        self._url = url

    @staticmethod
    def _redact_url_secret(message: str, url: str) -> str:
        import re

        redacted = re.sub(r"://([^:@/\s]+:)?[^@/\s]+@", "://***@", message)
        parsed = urlparse(url)
        if parsed.password:
            redacted = redacted.replace(parsed.password, "***")
        return redacted

    async def probe(self) -> ProbeResult:
        if not self._url:
            return _absent(self.name)
        import redis.asyncio

        start = time.perf_counter()
        client: Any = None
        try:
            client = redis.asyncio.from_url(self._url, socket_timeout=5.0, socket_connect_timeout=5.0)
            pong = await asyncio.wait_for(client.ping(), timeout=5.0)
            if pong:
                return _ok(self.name, "PING answered", start)
            return _absent(self.name, "Unexpected PING response", start)
        except Exception as exc:  # noqa: BLE001
            return _absent(self.name, self._redact_url_secret(str(exc), self._url), start)
        finally:
            if client is not None:
                try:
                    await client.aclose()
                except Exception:  # noqa: BLE001
                    pass


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
    """OTLP collector protocol/endpoint reachability."""

    name = "telemetry"

    def __init__(self, *, endpoint: str | None) -> None:
        self._endpoint = endpoint

    async def probe(self) -> ProbeResult:
        endpoint = self._endpoint.strip() if isinstance(self._endpoint, str) else ""
        if not endpoint:
            return _absent(self.name)
        start = time.perf_counter()
        parsed = urlparse(endpoint if "//" in endpoint else f"//{endpoint}")
        if parsed.scheme in {"http", "https"}:
            url = endpoint.rstrip("/")
            traces_url = url if url.endswith("/v1/traces") else f"{url}/v1/traces"
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(traces_url, json={"resourceSpans": []})
                code = int(resp.status_code)
                if 200 <= code < 300 or code in {400, 405, 415}:
                    return _ok(self.name, f"OTLP HTTP {code}", start)
                return _absent(self.name, f"OTLP HTTP {code}", start)
            except Exception as exc:  # noqa: BLE001
                return _absent(self.name, f"{type(exc).__name__}: {exc}", start)
        try:
            port = parsed.port or 4317
            _reader, writer = await asyncio.wait_for(asyncio.open_connection(parsed.hostname, port), timeout=5)
            writer.close()
            await writer.wait_closed()
            return _ok(self.name, "Collector reachable", start)
        except Exception as exc:  # noqa: BLE001
            return _absent(self.name, str(exc), start)


class AnalyticsCheck:
    """OpenPanel API readiness and client configuration check."""

    name = "analytics"

    def __init__(self, *, api_url: str | None, client_id: str | None = None) -> None:
        self._api_url = api_url
        self._client_id = client_id

    async def probe(self) -> ProbeResult:
        start = time.perf_counter()
        api_url = self._api_url.strip().rstrip("/") if isinstance(self._api_url, str) else ""
        if not api_url:
            return _absent(self.name, start=start)
        client_id = self._client_id.strip() if isinstance(self._client_id, str) else ""
        if not client_id:
            return _absent(self.name, "Missing OPENPANEL_CLIENT_ID", start)

        health_url = api_url if api_url.endswith("/healthcheck") else f"{api_url}/healthcheck"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(health_url)
            code = int(resp.status_code)
            if code != 200:
                return _absent(self.name, f"Analytics HTTP {code}", start)
            try:
                payload = resp.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict) and "ready" in payload and payload["ready"] is not True:
                return _absent(self.name, f"Analytics not ready: {payload}", start)
            return _ok(self.name, "Analytics HTTP 200", start)
        except Exception as exc:  # noqa: BLE001
            return _absent(self.name, f"{type(exc).__name__}: {exc}", start)


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
