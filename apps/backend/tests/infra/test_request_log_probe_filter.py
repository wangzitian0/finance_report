"""AC-observability.19.* (#2860): a successful probe request writes no request log line.

The request middleware in ``src.main`` logs one ``HTTP Request`` line per request. The
deploy health probe calls ``/health`` every 60 s, so those lines filled 94.5% of the
production log volume. These tests drive the real app (and the middleware function for
status-code boundaries) and capture the lines the middleware writes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import structlog
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request
from starlette.responses import Response

from src import main as main_module
from src.boot import Bootloader, ServiceStatus
from src.runtime.extension.api import health as health_api

pytestmark = pytest.mark.no_db

REQUEST_LOG_FIELDS = {"event", "level", "request_id", "method", "path", "status_code", "duration_ms"}


class _DummyAsyncSession:
    async def execute(self, *args, **kwargs):
        return None


class _DummyAsyncSessionContext:
    async def __aenter__(self):
        return _DummyAsyncSession()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


@pytest.fixture
def request_log(monkeypatch) -> list[dict]:
    """Replace the middleware logger with one that records every event dict it receives.

    The recorder has its own processor chain, so it does not depend on the global
    structlog configuration. ``merge_contextvars`` runs first, so the recorded dict holds
    the request-scoped fields the middleware binds (request_id, method, path).
    """
    entries: list[dict] = []

    def record(_logger, _method_name, event_dict):
        entries.append(dict(event_dict))
        raise structlog.DropEvent

    recording_logger = structlog.wrap_logger(
        None,
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            record,
        ],
    )
    monkeypatch.setattr(main_module, "logger", recording_logger)
    return entries


@pytest.fixture
def http_metrics(monkeypatch) -> list[dict]:
    """Record the arguments of every ``record_http_request`` call."""
    calls: list[dict] = []
    monkeypatch.setattr(main_module, "record_http_request", lambda **kwargs: calls.append(kwargs))
    return calls


@pytest_asyncio.fixture
async def app_client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=main_module.app), base_url="http://test") as client:
        yield client


def _stub_health_dependencies(monkeypatch, *, s3_status: str) -> None:
    """Make ``/health?full=1`` hermetic: every dependency probe is stubbed, S3 takes ``s3_status``."""
    monkeypatch.setattr(health_api, "_test_session_maker", lambda: _DummyAsyncSessionContext())
    probe_names = [name for name in dir(Bootloader) if name.startswith("_check_")]
    assert "_check_s3" in probe_names
    for name in probe_names:
        monkeypatch.setattr(Bootloader, name, AsyncMock(return_value=ServiceStatus(name, "ok", "OK")))
    monkeypatch.setattr(Bootloader, "_check_s3", AsyncMock(return_value=ServiceStatus("s3", s3_status, "stub")))


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("test", 80),
            "client": ("127.0.0.1", 50000),
        }
    )


async def test_AC_observability_19_1_successful_health_probe_writes_no_request_log_line(
    app_client: AsyncClient, request_log: list[dict], http_metrics: list[dict], monkeypatch
) -> None:
    """AC-observability.19.1: a 2xx ``/health`` request (liveness and ``?full=1`` readiness) logs nothing.

    The response still carries ``X-Request-ID`` and the RED request metric still counts the
    request: only the log line is dropped.
    """
    _stub_health_dependencies(monkeypatch, s3_status="ok")

    liveness = await app_client.get("/health")
    readiness = await app_client.get("/health?full=1")

    assert liveness.status_code == 200
    assert readiness.status_code == 200
    assert request_log == []
    assert liveness.headers["X-Request-ID"]
    assert readiness.headers["X-Request-ID"]
    assert [(call["status_code"], call["route"]) for call in http_metrics] == [(200, "/health"), (200, "/health")]


async def test_AC_observability_19_2_failed_health_probe_still_writes_request_log_line(
    app_client: AsyncClient, request_log: list[dict], monkeypatch
) -> None:
    """AC-observability.19.2: a 503 ``/health`` request writes its request log line."""
    _stub_health_dependencies(monkeypatch, s3_status="error")

    response = await app_client.get("/health?full=1")

    assert response.status_code == 503
    assert len(request_log) == 1
    line = request_log[0]
    assert line["event"] == "HTTP Request"
    assert line["status_code"] == 503
    assert line["path"] == "/health"
    assert line["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize("status_code", [200, 204, 299])
async def test_AC_observability_19_1_probe_with_2xx_status_writes_no_request_log_line(
    request_log: list[dict], status_code: int
) -> None:
    """AC-observability.19.1: every 2xx status of a probe path is quiet, including both range edges."""

    async def call_next(_request):
        return Response(status_code=status_code)

    response = await main_module.logging_middleware(_request("/health"), call_next)

    assert response.status_code == status_code
    assert request_log == []


@pytest.mark.parametrize("status_code", [300, 301, 400, 404, 500, 503])
async def test_AC_observability_19_2_probe_with_non_2xx_status_writes_request_log_line(
    request_log: list[dict], status_code: int
) -> None:
    """AC-observability.19.2: any non-2xx status of a probe path writes the request log line."""

    async def call_next(_request):
        return Response(status_code=status_code)

    await main_module.logging_middleware(_request("/health"), call_next)

    assert [(line["event"], line["status_code"]) for line in request_log] == [("HTTP Request", status_code)]


async def test_AC_observability_19_2_probe_that_raises_still_writes_failure_log_line(
    request_log: list[dict],
) -> None:
    """AC-observability.19.2: an unhandled exception on a probe path writes ``HTTP Request Failed``."""

    async def call_next(_request):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await main_module.logging_middleware(_request("/health"), call_next)

    assert [line["event"] for line in request_log] == ["HTTP Request Failed"]
    assert request_log[0]["path"] == "/health"


async def test_AC_observability_19_3_non_probe_request_keeps_its_request_log_line(
    app_client: AsyncClient, request_log: list[dict]
) -> None:
    """AC-observability.19.3: a 200 request to a non-probe path writes the same line as before #2860."""
    response = await app_client.get("/openapi.json")

    assert response.status_code == 200
    assert len(request_log) == 1
    line = request_log[0]
    assert set(line) == REQUEST_LOG_FIELDS
    assert line["event"] == "HTTP Request"
    assert line["level"] == "info"
    assert line["method"] == "GET"
    assert line["path"] == "/openapi.json"
    assert line["status_code"] == 200
    assert isinstance(line["duration_ms"], float)
    assert line["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize("path", ["/healthz", "/health/", "/api/health", "/healthcheck", "/ping"])
async def test_AC_observability_19_3_path_next_to_a_probe_path_keeps_its_request_log_line(
    request_log: list[dict], path: str
) -> None:
    """AC-observability.19.3: only the exact probe paths are quiet.

    Look-alike paths log a 200. ``/ping`` is the demo ping-pong state read (it queries the
    database and the UI uses it), not a liveness or readiness probe, so it also stays logged.
    """

    async def call_next(_request):
        return Response(status_code=200)

    await main_module.logging_middleware(_request(path), call_next)

    assert [(line["event"], line["path"], line["status_code"]) for line in request_log] == [("HTTP Request", path, 200)]


def test_AC_observability_19_1_probe_paths_are_routes_the_app_serves() -> None:
    """AC-observability.19.1: each quiet probe path is a route of the app, so the set cannot drift from the router."""
    served_paths = {getattr(route, "path", None) for route in main_module.app.routes}

    assert main_module._PROBE_PATHS
    assert main_module._PROBE_PATHS <= served_paths
