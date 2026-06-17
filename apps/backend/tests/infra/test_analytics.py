"""BE->OpenPanel server-side analytics emitter contract (Infra-014 / EPIC-024).

The 4th telemetry combination (backend product analytics). Uses the official
``openpanel`` Python SDK (symmetric with the FE ``@openpanel/nextjs``); the
contract here is the same posture as the FE: config-gated no-op, non-blocking,
never raises.
"""

from __future__ import annotations

from typing import Any

import pytest

from src import analytics
from src.config import settings


class _FakeOpenPanel:
    """Stand-in for the official openpanel SDK client. Records init args, global
    properties, and track() calls (the SDK sends on its own thread; here it's sync)."""

    instances: list[_FakeOpenPanel] = []

    def __init__(self, *, client_id: str, api_url: str | None = None, **kwargs: Any) -> None:
        self.client_id = client_id
        self.api_url = api_url
        self.global_properties: dict[str, Any] = {}
        self.tracked: list[tuple[str, dict[str, Any]]] = []
        type(self).instances.append(self)

    def set_global_properties(self, props: dict[str, Any]) -> None:
        self.global_properties.update(props)

    def track(self, name: str, properties: dict[str, Any] | None = None) -> None:
        self.tracked.append((name, properties or {}))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    # the emitter caches one module-level client; reset between tests
    monkeypatch.setattr(analytics, "_client", None)
    _FakeOpenPanel.instances = []
    # patch the official SDK symbol the module imports lazily
    import openpanel

    monkeypatch.setattr(openpanel, "OpenPanel", _FakeOpenPanel)
    yield
    monkeypatch.setattr(analytics, "_client", None)


def _configure(monkeypatch, *, client_id="6e8f9d85-test", api_url="https://openpanel.example/api", env="production"):
    monkeypatch.setattr(settings, "openpanel_client_id", client_id)
    monkeypatch.setattr(settings, "openpanel_api_url", api_url)
    monkeypatch.setattr(settings, "openpanel_environment", env)


def test_track_is_noop_when_unconfigured(monkeypatch) -> None:
    """No client-id (local/CI/preview) => complete no-op, SDK never built, returns False."""
    _configure(monkeypatch, client_id="")
    assert analytics.track("report_generated") is False
    assert _FakeOpenPanel.instances == []
    assert analytics.is_configured() is False


def test_track_uses_official_sdk_with_global_source_and_env(monkeypatch) -> None:
    """Configured => builds one SDK client (client_id + self-hosted api_url),
    stamps source=backend + deployment_environment globally, and tracks the event."""
    _configure(monkeypatch)

    assert analytics.track("report_generated", {"framework_id": "us_gaap_like"}) is True

    assert len(_FakeOpenPanel.instances) == 1
    client = _FakeOpenPanel.instances[0]
    assert client.client_id == "6e8f9d85-test"
    assert client.api_url == "https://openpanel.example/api"
    assert client.global_properties == {"source": "backend", "deployment_environment": "production"}
    assert client.tracked == [("report_generated", {"framework_id": "us_gaap_like"})]


def test_client_is_built_once_across_calls(monkeypatch) -> None:
    """The SDK spins a daemon thread; the emitter must reuse ONE client, not one-per-event."""
    _configure(monkeypatch)
    analytics.track("a")
    analytics.track("b")
    assert len(_FakeOpenPanel.instances) == 1
    assert [n for n, _ in _FakeOpenPanel.instances[0].tracked] == ["a", "b"]


def test_track_never_raises_when_sdk_errors(monkeypatch) -> None:
    """An SDK error is swallowed (returns False) — analytics must never break the request."""
    _configure(monkeypatch)

    class _BoomOpenPanel(_FakeOpenPanel):
        def track(self, *a: Any, **k: Any) -> None:
            raise RuntimeError("sdk boom")

    import openpanel

    monkeypatch.setattr(openpanel, "OpenPanel", _BoomOpenPanel)
    assert analytics.track("report_generated") is False
