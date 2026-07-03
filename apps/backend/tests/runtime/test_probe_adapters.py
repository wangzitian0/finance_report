"""AC-runtime.4.1 (#1580) — probe adapters for the five declared-but-unprobed dependencies.

cache (Redis), workflow_engine (Prefect), telemetry (OTel), analytics (OpenPanel)
and market_data (Yahoo) each get a `DependencyCheck` adapter, so every declared
dependency's presence can be asserted (invariant 2 becomes enforceable for the
whole manifest). Probes are binary PRESENT/ABSENT, never raise for an outage,
and 'not configured' is ABSENT — there is no `skipped`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.runtime import (
    AnalyticsCheck,
    DependencyStatus,
    MarketDataCheck,
    RedisCheck,
    TelemetryCheck,
    WorkflowEngineCheck,
)

pytestmark = pytest.mark.no_db


def _http_response(status_code: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    return resp


class TestRedisCheck:
    async def test_unconfigured_is_absent(self):
        result = await RedisCheck(url=None).probe()
        assert result.status is DependencyStatus.ABSENT
        assert result.name == "cache"

    async def test_pong_is_present(self):
        reader = AsyncMock()
        reader.readline.return_value = b"+PONG\r\n"
        writer = MagicMock()
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()
        with patch("asyncio.open_connection", AsyncMock(return_value=(reader, writer))):
            result = await RedisCheck(url="redis://cache:6379/0").probe()
        assert result.status is DependencyStatus.PRESENT

    async def test_connection_refused_is_absent(self):
        with patch("asyncio.open_connection", AsyncMock(side_effect=ConnectionRefusedError("refused"))):
            result = await RedisCheck(url="redis://cache:6379/0").probe()
        assert result.status is DependencyStatus.ABSENT


class TestWorkflowEngineCheck:
    async def test_unconfigured_is_absent(self):
        result = await WorkflowEngineCheck(api_url=None).probe()
        assert result.status is DependencyStatus.ABSENT
        assert result.name == "workflow_engine"

    async def test_healthy_api_is_present(self):
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=_http_response(200))):
            result = await WorkflowEngineCheck(api_url="http://prefect:4200/api").probe()
        assert result.status is DependencyStatus.PRESENT

    async def test_unreachable_api_is_absent(self):
        import httpx

        with patch("httpx.AsyncClient.get", AsyncMock(side_effect=httpx.ConnectError("down"))):
            result = await WorkflowEngineCheck(api_url="http://prefect:4200/api").probe()
        assert result.status is DependencyStatus.ABSENT


class TestTelemetryCheck:
    async def test_unconfigured_is_absent(self):
        result = await TelemetryCheck(endpoint=None).probe()
        assert result.status is DependencyStatus.ABSENT
        assert result.name == "telemetry"

    async def test_reachable_collector_is_present(self):
        writer = MagicMock()
        writer.wait_closed = AsyncMock()
        with patch("asyncio.open_connection", AsyncMock(return_value=(AsyncMock(), writer))):
            result = await TelemetryCheck(endpoint="http://otel-collector:4318").probe()
        assert result.status is DependencyStatus.PRESENT

    async def test_unreachable_collector_is_absent(self):
        with patch("asyncio.open_connection", AsyncMock(side_effect=OSError("no route"))):
            result = await TelemetryCheck(endpoint="http://otel-collector:4318").probe()
        assert result.status is DependencyStatus.ABSENT


class TestAnalyticsCheck:
    async def test_unconfigured_is_absent(self):
        result = await AnalyticsCheck(api_url="").probe()
        assert result.status is DependencyStatus.ABSENT
        assert result.name == "analytics"

    async def test_responding_service_is_present(self):
        # Any HTTP response < 500 proves the service is there (a 404 on the
        # root path is still a reachable OpenPanel).
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=_http_response(404))):
            result = await AnalyticsCheck(api_url="https://op.example.com/api").probe()
        assert result.status is DependencyStatus.PRESENT

    async def test_server_error_is_absent(self):
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=_http_response(503))):
            result = await AnalyticsCheck(api_url="https://op.example.com/api").probe()
        assert result.status is DependencyStatus.ABSENT


class TestMarketDataCheck:
    async def test_responding_yahoo_is_present(self):
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=_http_response(200))):
            result = await MarketDataCheck(timeout_seconds=5).probe()
        assert result.status is DependencyStatus.PRESENT
        assert result.name == "market_data"

    async def test_rate_limited_yahoo_is_still_present(self):
        # 429 means Yahoo is up and talking to us; presence ≠ quota.
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=_http_response(429))):
            result = await MarketDataCheck(timeout_seconds=5).probe()
        assert result.status is DependencyStatus.PRESENT

    async def test_unreachable_yahoo_is_absent(self):
        import httpx

        with patch("httpx.AsyncClient.get", AsyncMock(side_effect=httpx.ConnectError("down"))):
            result = await MarketDataCheck(timeout_seconds=5).probe()
        assert result.status is DependencyStatus.ABSENT


def test_AC_runtime_4_1_every_declared_dependency_has_a_probe_adapter():
    """AC-runtime.4.1 (#1580): the manifest has no declared-but-unprobed
    dependency left — Bootloader._required_checks finds a probe for every
    declared dependency in every tier (invariant 2 is enforceable everywhere)."""
    from src.boot import Bootloader
    from src.runtime import EnvTier

    for tier in EnvTier:
        _probed, unprobed = Bootloader._required_checks(tier)
        assert unprobed == [], f"{tier.value}: unprobed {unprobed}"
