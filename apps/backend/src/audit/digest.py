"""Canonical JSON and UTF-8 text SHA-256 digests (#2768)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any


def canonical_json_digest(value: object, *, default: Callable[[Any], Any] | None = None) -> str:
    """Return the SHA-256 hex digest of the canonical JSON text of ``value``."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=default).encode()
    ).hexdigest()


def text_digest(text: str) -> str:
    """Return the SHA-256 hex digest of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode()).hexdigest()
