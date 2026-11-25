from __future__ import annotations

import types
from typing import Any

from src.config import settings
from src.observability import analytics


def test_track_noop_posts_and_ignores_transport_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        analytics.threading, "Thread", lambda target, args=(), **_kw: types.SimpleNamespace(start=lambda: target(*args))
    )
    for k, v in (
        ("openpanel_client_id", ""),
        ("openpanel_api_url", "https://openpanel.example/api"),
        ("openpanel_environment", "production"),
    ):
        monkeypatch.setattr(settings, k, v)
    posted: list[Any] = []
    monkeypatch.setattr(analytics, "_post", lambda *a: posted.append(a))
    assert analytics.track("report_generated") is False and posted == [] and analytics.is_configured() is False

    monkeypatch.setattr(settings, "openpanel_client_id", "62d5cfe0-test")
    assert analytics.track("report_generated", {"framework_id": "us_gaap_like"}) is True and len(posted) == 1
    body, cid, ep = posted[0]
    assert (ep, cid, body["type"], body["payload"]["name"]) == (
        "https://openpanel.example/api/track",
        "62d5cfe0-test",
        "track",
        "report_generated",
    )
    assert "profileId" not in body["payload"] and body["payload"]["properties"] == {
        "source": "backend",
        "deployment_environment": "production",
        "framework_id": "us_gaap_like",
    }


def test_track_never_raises_on_transport_error(monkeypatch) -> None:
    monkeypatch.setattr(
        analytics.threading, "Thread", lambda target, args=(), **_kw: types.SimpleNamespace(start=lambda: target(*args))
    )
    for k, v in (
        ("openpanel_client_id", "62d5cfe0-test"),
        ("openpanel_api_url", "https://openpanel.example/api"),
        ("openpanel_environment", "production"),
    ):
        monkeypatch.setattr(settings, k, v)
    cm = types.SimpleNamespace(
        __enter__=lambda s: s,
        __exit__=lambda *_a: False,
        post=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("connection refused")),
    )
    monkeypatch.setattr("httpx.Client", lambda *_a, **_k: cm)
    assert analytics.track("report_generated") is True
