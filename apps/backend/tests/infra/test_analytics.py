"""BE->OpenPanel server-side analytics emitter contract (EPIC-024 AC24.2.2).

AC24.2.2 ("the analytics layer actually dispatches an OpenPanel event") realized
SERVER-SIDE — the 4th telemetry combination (backend product analytics). A thin REST
client (NOT the official openpanel SDK, which sends profileId=null and 400s against our
self-hosted instance — see src/observability/analytics.py). Same posture as the FE: config-gated
no-op, non-blocking, never raises.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.config import settings
from src.observability import analytics


class _ImmediateThread:
    """Run the daemon-thread target synchronously so the POST is observable in-test."""

    def __init__(self, target=None, args=(), daemon=None, **_kw: Any) -> None:
        self._target = target
        self._args = args

    def start(self) -> None:
        self._target(*self._args)


@pytest.fixture(autouse=True)
def _sync_threads(monkeypatch):
    monkeypatch.setattr(analytics.threading, "Thread", _ImmediateThread)


def _configure(monkeypatch, *, client_id="62d5cfe0-test", api_url="https://openpanel.example/api", env="production"):
    monkeypatch.setattr(settings, "openpanel_client_id", client_id)
    monkeypatch.setattr(settings, "openpanel_api_url", api_url)
    monkeypatch.setattr(settings, "openpanel_environment", env)


def test_track_is_noop_when_unconfigured(monkeypatch) -> None:
    """No client-id (local/CI/preview) => complete no-op, no POST, returns False."""
    _configure(monkeypatch, client_id="")
    posted: list[Any] = []
    monkeypatch.setattr(analytics, "_post", lambda *a: posted.append(a))
    assert analytics.track("report_generated") is False
    assert posted == []
    assert analytics.is_configured() is False


def test_track_posts_to_track_endpoint_with_client_id_and_no_profileid(monkeypatch) -> None:
    """Configured => POSTs {type:track, payload:{name, properties}} to <api>/track with the
    openpanel-client-id header; tags source=backend + deployment_environment; and crucially
    OMITS profileId (the field the official SDK sends as null, which our OpenPanel 400s on)."""
    _configure(monkeypatch)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        analytics,
        "_post",
        lambda payload, cid, endpoint: calls.append({"payload": payload, "cid": cid, "endpoint": endpoint}),
    )

    assert analytics.track("report_generated", {"framework_id": "us_gaap_like"}) is True
    assert len(calls) == 1
    c = calls[0]
    assert c["endpoint"] == "https://openpanel.example/api/track"
    assert c["cid"] == "62d5cfe0-test"
    body = c["payload"]
    assert body["type"] == "track"
    assert "profileId" not in body["payload"]
    assert body["payload"]["name"] == "report_generated"
    props = body["payload"]["properties"]
    assert props["source"] == "backend"
    assert props["deployment_environment"] == "production"
    assert props["framework_id"] == "us_gaap_like"


def test_track_never_raises_on_transport_error(monkeypatch) -> None:
    """A transport/HTTP error inside _post is swallowed — analytics must never break the
    request that scheduled it (track still returns True; the failure is logged at debug)."""
    _configure(monkeypatch)

    class _BoomClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a: Any, **k: Any):
            raise RuntimeError("connection refused")

    # httpx is imported lazily inside _post (tooling envs load the observability
    # package without backend deps), so patch the library itself.
    monkeypatch.setattr("httpx.Client", lambda *a, **k: _BoomClient())
    assert analytics.track("report_generated") is True
