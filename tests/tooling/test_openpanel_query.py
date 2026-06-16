"""Tests for tools/openpanel_query.py (EPIC-023 / AC23.1.4).

The OpenPanel query CLI lives in the repo-root ``tools/`` package (the
registered home for Python governance / CI tooling). It is stdlib-only and is
loaded by file path here so the import does not depend on package wiring.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = REPO_ROOT / "tools" / "openpanel_query.py"


def _load_cli() -> ModuleType:
    spec = importlib.util.spec_from_file_location("openpanel_query", CLI_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = _load_cli()


def test_AC23_1_4_cli_module_and_help_smoke() -> None:
    """AC23.1.4: the OpenPanel query CLI exists and exposes events/funnel."""
    assert CLI_PATH.exists()
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
