"""``platform.extension.rate_limit`` — the shared in-memory request rate limiter.

Request rate-limiting is cross-cutting runtime middleware: an impure,
process-global service that throttles inbound requests per key (typically client
IP). It therefore lives in the ``platform`` package's ``extension`` layer (the
impure edge), alongside the other runtime middleware adapters.

SECURITY: Protects against brute-force and request-flood attacks. Uses in-memory
storage with a sliding-window algorithm.

NOTE: This implementation uses in-memory, per-process storage. In a multi-instance
deployment (e.g. multiple workers/containers behind a load balancer), each
instance maintains its own counters, effectively multiplying the allowed requests
by the number of instances. For single-instance deployment this is sufficient.

Threading note: We use ``threading.Lock`` rather than ``asyncio.Lock`` because the
critical section is very short (dict operations only). This is acceptable for
FastAPI/uvicorn as the lock is held for microseconds and won't block the event
loop meaningfully.

The app-wide ``api_rate_limiter`` instance (the global API throttle) is config-
bound, so it is wired at the composition root (``src.main``) from this package's
:class:`RateLimiter` / :class:`RateLimitConfig` — this package stays config-free.
Identity's auth-specific limiters live in the ``identity`` package
(``src.identity.extension.rate_limit``, #1428); they import :class:`RateLimiter` /
:class:`RateLimitConfig` from the published root.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class RateLimitConfig:
    """Rate limit configuration."""

    max_requests: int = 5  # Maximum requests in window
    window_seconds: int = 60  # Time window in seconds
    block_seconds: int = 300  # Block duration after exceeding limit


@dataclass
class RateLimitState:
    """State for a single IP/key."""

    requests: list[float] = field(default_factory=list)
    blocked_until: float = 0.0


class RateLimiter:
    """In-memory rate limiter using sliding window algorithm.

    Thread-safe for concurrent access.
    """

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        self.config = config or RateLimitConfig()
        self._local_state: dict[str, RateLimitState] = defaultdict(RateLimitState)
        self._lock = Lock()

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """Check if request is allowed for the given key."""
        now = time.time()
        with self._lock:
            state = self._local_state[key]
            if state.blocked_until > now:
                return False, max(1, math.ceil(state.blocked_until - now))

            window_start = now - self.config.window_seconds
            state.requests = [ts for ts in state.requests if ts >= window_start]

            if len(state.requests) >= self.config.max_requests:
                state.blocked_until = now + self.config.block_seconds
                return False, self.config.block_seconds

            state.requests.append(now)
            return True, 0

    def reset(self, key: str) -> None:
        """Reset rate limit state for a key."""
        with self._lock:
            if key in self._local_state:
                del self._local_state[key]

    def clear(self) -> None:
        """Drop all rate-limit state (every key). Used for test isolation."""
        with self._lock:
            self._local_state.clear()
