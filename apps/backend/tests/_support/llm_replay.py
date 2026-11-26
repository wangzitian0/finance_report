"""Replay of recorded model calls: the matcher, the config and the marker check (#3153).

A recording is a VCR cassette. `pytest --record-mode=none` (the default of a run) replays it and blocks the
network. `LLM_API_KEY=<key> pytest --record-mode=rewrite <test>` records it again.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
from pydantic_ai import models

_VCR_FILTER_HEADERS = (
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "api-key",
    "x-goog-api-key",
    "cookie",
    "set-cookie",
)
_VCR_FILTER_QUERY_PARAMS = (
    "key",
    "api_key",
    "apikey",
    "token",
    "access_token",
    "secret",
    "password",
    "auth",
    "sig",
    "signature",
)
_HEADER_REDACT = frozenset(_VCR_FILTER_HEADERS)
_QUERY_REDACT = frozenset(_VCR_FILTER_QUERY_PARAMS)


def _scrub_url(raw: str) -> str:
    parts = urlsplit(raw)
    if not parts.query:
        return raw
    pairs = [
        (k, "REDACTED" if k.lower() in _QUERY_REDACT else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


def _scrub_headers(headers: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in headers.items():
        if str(k).lower() in _HEADER_REDACT:
            out[k] = ["REDACTED"] if isinstance(v, list) else "REDACTED"
        else:
            out[k] = v
    return out


def _scrub_text(text: str) -> str:
    cleaned = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", text)
    ambient_key = os.environ.get("LLM_API_KEY", "").strip()
    if ambient_key:
        cleaned = cleaned.replace(ambient_key, "[REDACTED]")
    return cleaned


def _scrub_body(body: Any) -> Any:
    if isinstance(body, dict) and isinstance(body.get("string"), str):
        return {**body, "string": _scrub_text(body["string"])}
    if isinstance(body, str):
        return _scrub_text(body)
    return body


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
    def _before_record_request(request: Any) -> Any:
        if getattr(request, "uri", None):
            request.uri = _scrub_url(str(request.uri))
        if getattr(request, "headers", None):
            request.headers = _scrub_headers(dict(request.headers))
        if getattr(request, "body", None) is not None:
            request.body = _scrub_body(request.body)
        return request

    def _before_record_response(response: dict[str, Any]) -> dict[str, Any]:
        hdrs = response.get("headers")
        if isinstance(hdrs, Mapping):
            response["headers"] = _scrub_headers(hdrs)
        if "body" in response:
            response["body"] = _scrub_body(response["body"])
        return response

    return {
        "filter_headers": [(h, "REDACTED") for h in _VCR_FILTER_HEADERS],
        "filter_query_parameters": [(q, "REDACTED") for q in _VCR_FILTER_QUERY_PARAMS],
        "decode_compressed_response": True,
        "match_on": ("method", "scheme", "host", "port", "path", "query", "llm_body"),
        "before_record_request": _before_record_request,
        "before_record_response": _before_record_response,
    }


@contextmanager
def allow_vcr_model_requests() -> Iterator[None]:
    """Temporarily allow model dispatch inside @pytest.mark.vcr while vcrpy blocks sockets."""
    with models.override_allow_model_requests(True):
        yield


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
