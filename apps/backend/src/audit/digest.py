"""Canonical JSON and UTF-8 text SHA-256 digests (#2768)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from infra2_sdk._wire import canonical_sha256


def canonical_json_digest(value: object, *, default: Callable[[Any], Any] | None = None) -> str:
    """Return the SHA-256 hex digest of the canonical JSON text of ``value``."""
    if default is None:
        return canonical_sha256(value)
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=default).encode()
    ).hexdigest()


def text_digest(text: str) -> str:
    """Return the SHA-256 hex digest of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode()).hexdigest()
