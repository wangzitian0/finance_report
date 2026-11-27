from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi.routing import iter_route_contexts
from httpx import ASGITransport, AsyncClient

from src import main as main_module
from src.boot import Bootloader, ServiceStatus

PROBE_PATHS = main_module._PROBE_PATHS

pytestmark = pytest.mark.no_db


@pytest_asyncio.fixture
async def app_client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=main_module.app), base_url="http://test") as client:
        yield client


def _stub_health(monkeypatch, *, s3_status: str) -> None:
    for name in (n for n in dir(Bootloader) if n.startswith("_check_")):
        monkeypatch.setattr(
            Bootloader,
            name,
            AsyncMock(return_value=ServiceStatus(name, s3_status if name == "_check_s3" else "ok", "stub")),
        )


@pytest.mark.parametrize(
    ("s3_status", "paths", "expected_code"),
    [("ok", ("/livez", "/readyz", "/health?full=1"), 200), ("error", ("/health?full=1",), 503)],
)
async def test_AC_observability_19_1_and_2_health_probes(
    app_client: AsyncClient, monkeypatch, s3_status: str, paths: tuple[str, ...], expected_code: int
) -> None:
    _stub_health(monkeypatch, s3_status=s3_status)
    for path in paths:
        resp = await app_client.get(path)
        assert resp.status_code == expected_code and resp.headers["X-Request-ID"]


def test_AC_observability_19_1_and_3_probe_access_filter_and_routes() -> None:
    flt = next(f for f in logging.getLogger("uvicorn.access").filters if getattr(f, "_infra2_probe_filter", False))
    make_rec = lambda p: logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', ("127.0.0.1", "GET", p, "1.1", 200), None
    )
    assert all(flt.filter(make_rec(p)) is False for p in PROBE_PATHS | {"/api/health"})
    assert all(
        flt.filter(make_rec(p)) is True
        for p in ("/openapi.json", "/healthz", "/health/", "/api/users", "/healthcheck", "/ping")
    )
    served = {getattr(ctx.route, "path", None) for ctx in iter_route_contexts(main_module.app.routes)}
    assert (
        main_module._PROBE_PATHS
        and main_module._PROBE_PATHS <= served
        and main_module._RATE_LIMIT_EXEMPT_PATHS <= served
    )
