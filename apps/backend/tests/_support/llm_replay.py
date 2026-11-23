"""Replay of recorded model calls: the matcher, the config and the marker check (#3153).

A recording is a VCR cassette. `pytest --record-mode=none` (the default of a run) replays it and blocks the
network. `LLM_API_KEY=<key> pytest --record-mode=rewrite <test>` records it again.
"""

from __future__ import annotations

import json
from typing import Any

import pytest


def _body(request: Any) -> Any:
    raw = request.body
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return raw


def llm_body_matches(recorded: Any, sent: Any) -> None:
    """A recording answers only the request that it was recorded for: the JSON bodies must be equal.

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
