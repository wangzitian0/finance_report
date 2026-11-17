from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi.routing import iter_route_contexts
from httpx import ASGITransport, AsyncClient
from infra2_sdk.fastapi import _ProbeAccessFilter
from infra2_sdk.runtime.otel import PROBE_PATHS

from src import main as main_module
from src.boot import Bootloader, ServiceStatus

pytestmark = pytest.mark.no_db


@pytest_asyncio.fixture
async def app_client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=main_module.app), base_url="http://test") as client:
        yield client


def _stub_health_dependencies(monkeypatch, *, s3_status: str) -> None:
    probe_names = [name for name in dir(Bootloader) if name.startswith("_check_")]
    assert "_check_s3" in probe_names
    for name in probe_names:
        monkeypatch.setattr(Bootloader, name, AsyncMock(return_value=ServiceStatus(name, "ok", "OK")))
    monkeypatch.setattr(Bootloader, "_check_s3", AsyncMock(return_value=ServiceStatus("s3", s3_status, "stub")))


async def test_AC_observability_19_1_successful_health_probe_sets_request_id_and_suppresses_access_logs(
    app_client: AsyncClient, monkeypatch
) -> None:
    "AC-observability.19.1"
    _stub_health_dependencies(monkeypatch, s3_status="ok")
    liveness = await app_client.get("/livez")
    readiness = await app_client.get("/readyz")
    health = await app_client.get("/health?full=1")
    assert liveness.status_code == 200
    assert readiness.status_code == 200
    assert health.status_code == 200
    assert liveness.headers["X-Request-ID"]
    assert readiness.headers["X-Request-ID"]
    assert health.headers["X-Request-ID"]
    flt = _ProbeAccessFilter()
    for path in PROBE_PATHS:
        rec = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            "",
            0,
            '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1", "GET", path, "1.1", 200),
            None,
        )
        assert flt.filter(rec) is False


async def test_AC_observability_19_2_failed_health_probe_returns_503_with_request_id(
    app_client: AsyncClient, monkeypatch
) -> None:
    "AC-observability.19.2"
    _stub_health_dependencies(monkeypatch, s3_status="error")
    response = await app_client.get("/health?full=1")
    assert response.status_code == 503
    assert response.headers["X-Request-ID"]


@pytest.mark.parametrize("path", ["/openapi.json", "/healthz", "/health/", "/api/health", "/healthcheck", "/ping"])
def test_AC_observability_19_3_non_probe_path_keeps_uvicorn_access_log(path: str) -> None:
    "AC-observability.19.3"
    flt = _ProbeAccessFilter()
    rec = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', ("127.0.0.1", "GET", path, "1.1", 200), None
    )
    assert flt.filter(rec) is True


def test_AC_observability_19_1_probe_paths_are_routes_the_app_serves() -> None:
    """AC-observability.19.1: probe and rate-limit exempt paths must be served routes."""
    served_paths = {getattr(context.route, "path", None) for context in iter_route_contexts(main_module.app.routes)}
    assert main_module._PROBE_PATHS
    assert main_module._PROBE_PATHS <= served_paths
    assert main_module._RATE_LIMIT_EXEMPT_PATHS <= served_paths
