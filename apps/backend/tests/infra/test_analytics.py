"""BE->OpenPanel server-side analytics emitter contract (Infra-014 / EPIC-024).

The 4th telemetry combination (backend product analytics). Mirrors the FE
``src/lib/analytics.ts`` posture: config-gated no-op, non-blocking, never raises.
"""

from __future__ import annotations

from typing import Any

import pytest

from src import analytics
from src.config import settings


class _FakeResponse:
    def __init__(self, status: int = 200) -> None:
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("bad", request=None, response=None)


class _FakeAsyncClient:
    """Records the single POST track() makes, as an async context manager."""

    calls: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        type(self).calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse(200)


@pytest.fixture(autouse=True)
def _reset_calls():
    _FakeAsyncClient.calls = []
    yield
    _FakeAsyncClient.calls = []


def _configure(monkeypatch, *, client_id="6e8f9d85-test", api_url="https://openpanel.example/api", env="production"):
    monkeypatch.setattr(settings, "openpanel_client_id", client_id)
    monkeypatch.setattr(settings, "openpanel_api_url", api_url)
    monkeypatch.setattr(settings, "openpanel_environment", env)


async def test_track_is_noop_when_unconfigured(monkeypatch) -> None:
    """No client-id (local/CI/preview) => complete no-op, no HTTP, returns False."""
    _configure(monkeypatch, client_id="")
    monkeypatch.setattr(analytics.httpx, "AsyncClient", _FakeAsyncClient)
    assert await analytics.track("report_generated") is False
    assert _FakeAsyncClient.calls == []
    assert analytics.is_configured() is False


async def test_track_posts_to_openpanel_track_with_client_id_header(monkeypatch) -> None:
    """Configured => POSTs {type:track, payload:{name, properties}} to <api>/track
    with the openpanel-client-id header; tags source=backend + deployment_environment."""
    _configure(monkeypatch)
    monkeypatch.setattr(analytics.httpx, "AsyncClient", _FakeAsyncClient)

    assert await analytics.track("report_generated", {"framework_id": "us_gaap_like"}) is True
    assert len(_FakeAsyncClient.calls) == 1
    call = _FakeAsyncClient.calls[0]
    assert call["url"] == "https://openpanel.example/api/track"
    assert call["headers"]["openpanel-client-id"] == "6e8f9d85-test"
    body = call["json"]
    assert body["type"] == "track"
    assert body["payload"]["name"] == "report_generated"
    props = body["payload"]["properties"]
    assert props["source"] == "backend"
    assert props["deployment_environment"] == "production"
    assert props["framework_id"] == "us_gaap_like"


async def test_track_never_raises_on_transport_error(monkeypatch) -> None:
    """A transport/HTTP error is swallowed (returns False) — analytics must never
    break the request that scheduled it."""
    _configure(monkeypatch)

    class _BoomClient(_FakeAsyncClient):
        async def post(self, *a: Any, **k: Any):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(analytics.httpx, "AsyncClient", _BoomClient)
    assert await analytics.track("report_generated") is False
