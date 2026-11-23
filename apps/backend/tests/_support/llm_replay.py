"""Replay of recorded model calls: the matcher, the config and the marker check (#3153).

A recording is a VCR cassette. `pytest --record-mode=none` (the default of a run) replays it and blocks the
network. `LLM_API_KEY=<key> pytest --record-mode=rewrite <test>` records it again.
"""

from __future__ import annotations

import json
from typing import Any

import pytest


def _body(request: Any) -> tuple[str, Any]:
    """Return the body of a request in a form that compares exactly: JSON as canonical text, else the raw bytes.

    ``True`` and ``1``, or ``20`` and ``20.0``, are different values of a request. An empty body and ``null`` are
    different too.
    """
    raw = request.body
    if raw is None:
        return ("none", None)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    try:
        return ("json", json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")))
    except ValueError:
        return ("raw", bytes(raw))


def llm_body_matches(recorded: Any, sent: Any) -> None:
    """A recording answers only the request that it was recorded for: the bodies must be equal.

    The check raises by hand. An `assert` of a conftest module builds the full diff of two large bodies at each
    candidate of a recording.
    """
    if _body(recorded) != _body(sent):
        raise AssertionError("the request body differs from the recorded request body")


def llm_vcr_config() -> dict[str, Any]:
    from infra2_sdk.runtime import vcr_llm_config

    config = vcr_llm_config()
    config["match_on"] = (*config["match_on"], "llm_body")
    return config


def require_vcr_marker(request: Any) -> None:
    """Fail a test that lifts the model block without a cassette: its request would reach the provider."""
    if request.node.get_closest_marker("vcr") is None:
        pytest.fail(
            "vcr_llm needs @pytest.mark.vcr on the test: without a cassette the request would go out", pytrace=False
        )
    if request.config.getoption("--disable-recording", default=False):
        pytest.fail(
            "--disable-recording turns the cassette off: a vcr_llm test would reach the provider", pytrace=False
        )
