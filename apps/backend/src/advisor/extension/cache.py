"""Response cache (TTL) for advisor answers.

Moved from ``src/services/ai_advisor/_cache.py`` (#1671 Wave B).  A domain
service (deterministic dedup by question + context hash + model), so it lives
in ``extension/`` per the package model's kind table.
"""

from __future__ import annotations

import time

from src.advisor.base.constants import CACHE_TTL_SECONDS


class ResponseCache:
    """Simple in-memory cache for common answers."""

    def __init__(self, ttl_seconds: int = CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, str]] = {}

    def get(self, key: str) -> str | None:
        now = time.time()
        entry = self._store.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if now >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str) -> None:
        expires_at = time.time() + self._ttl
        self._store[key] = (expires_at, value)

    def prune(self) -> None:
        now = time.time()
        expired = [key for key, (exp, _) in self._store.items() if exp <= now]
        for key in expired:
            self._store.pop(key, None)


_CACHE = ResponseCache()
