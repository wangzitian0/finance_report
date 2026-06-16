"""Tests for the OpenPanel query CLI (EPIC-023 / AC23.1.4).

Logic lives in ``common.observability.openpanel_query`` (measured under the
``common`` coverage component); ``tools/openpanel_query.py`` is a thin wrapper.
"""

from __future__ import annotations

import argparse
import io
import json

import pytest

from common.observability import openpanel_query as cli


def test_AC23_1_4_cli_module_and_help_smoke() -> None:
    """AC23.1.4: the OpenPanel query CLI exists and exposes events/funnel."""
    parser = cli.build_parser()
    assert isinstance(parser, argparse.ArgumentParser)
    # --help must exit cleanly (smoke).
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--help"])
    assert exc.value.code == 0


def test_AC23_1_4_api_key_read_from_env_not_args() -> None:
    """AC23.1.4: the API key comes from OPENPANEL_API_KEY, never a CLI flag."""
    assert "--api-key" not in cli.build_parser().format_help()
    assert cli.resolve_api_key({"OPENPANEL_API_KEY": "abc"}) == "abc"
    with pytest.raises(SystemExit):
        cli.resolve_api_key({})


def test_AC23_1_4_env_filter_and_funnel_payload() -> None:
    """AC23.1.4: --env filters by environment; funnel steps are split/trimmed."""
    events_ns = argparse.Namespace(
        command="events", env="staging", limit=50, event="upload_clicked", api_url=None
    )
    payload = cli.build_payload(events_ns)
    assert payload["event"] == "upload_clicked"
    assert payload["limit"] == 50
    assert payload["filters"] == [
        {"name": "environment", "operator": "is", "value": ["staging"]}
    ]

    funnel_ns = argparse.Namespace(
        command="funnel", env=None, limit=10, steps="a, b , ,c", api_url=None
    )
    funnel_payload = cli.build_payload(funnel_ns)
    assert funnel_payload["steps"] == ["a", "b", "c"]
    assert "filters" not in funnel_payload


def test_AC23_1_4_run_uses_resolved_endpoint_and_injected_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC23.1.4: run() targets <api-url>/<command> with the env-sourced key."""
    monkeypatch.setenv("OPENPANEL_API_KEY", "secret-key")
    captured: dict[str, object] = {}

    def fake_transport(
        url: str, key: str, payload: dict[str, object]
    ) -> dict[str, object]:
        captured["url"] = url
        captured["key"] = key
        captured["payload"] = payload
        return {"ok": True}

    ns = argparse.Namespace(
        command="events",
        env="production",
        limit=5,
        event=None,
        api_url="https://op.example/api/",
    )
    result = cli.run(ns, transport=fake_transport)
    assert result == {"ok": True}
    assert captured["url"] == "https://op.example/api/events"
    assert captured["key"] == "secret-key"
    assert captured["payload"]["event"] == "*"


def test_AC23_1_4_resolve_api_url_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC23.1.4: explicit flag > OPENPANEL_API_URL env > self-hosted default."""
    monkeypatch.delenv("OPENPANEL_API_URL", raising=False)
    assert cli.resolve_api_url(None) == cli.DEFAULT_API_URL
    monkeypatch.setenv("OPENPANEL_API_URL", "https://env.example/api")
    assert cli.resolve_api_url(None) == "https://env.example/api"
    assert cli.resolve_api_url("https://flag.example/api") == "https://flag.example/api"


def test_AC23_1_4_main_prints_json_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC23.1.4: main() resolves config, runs the request, and prints JSON."""
    monkeypatch.setenv("OPENPANEL_API_KEY", "secret-key")
    monkeypatch.setattr(
        cli, "post_json", lambda url, key, payload: {"events": [], "url": url}
    )
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    rc = cli.main(["--env", "staging", "events"])
    assert rc == 0
    printed = json.loads(out.getvalue())
    assert printed["url"].endswith("/events")


def test_AC23_1_4_main_reports_network_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC23.1.4: a transport URLError is reported as a non-zero exit, not a crash."""
    import urllib.error

    monkeypatch.setenv("OPENPANEL_API_KEY", "secret-key")

    def boom(url: str, key: str, payload: dict[str, object]) -> dict[str, object]:
        raise urllib.error.URLError("down")

    monkeypatch.setattr(cli, "post_json", boom)
    err = io.StringIO()
    monkeypatch.setattr("sys.stderr", err)
    rc = cli.main(["funnel", "--steps", "a,b"])
    assert rc == 1
    assert "failed" in err.getvalue()
