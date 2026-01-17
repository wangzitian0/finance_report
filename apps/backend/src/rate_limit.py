"""Rate limiting for authentication endpoints.

SECURITY: Protects against brute-force attacks on /login and /register endpoints.
Uses in-memory storage with sliding window algorithm.

NOTE: This implementation uses in-memory, per-process storage. In a multi-instance
deployment (e.g., multiple workers/containers behind a load balancer), each instance
maintains its own counters, effectively multiplying the allowed requests by the
number of instances.

For production-grade, distributed rate limiting, use a shared backend such as Redis
to store rate limit state centrally, or ensure single-instance deployment for auth.

Threading note: We use threading.Lock rather than asyncio.Lock because the critical
section is very short (dict operations only). This is acceptable for FastAPI/uvicorn
as the lock is held for microseconds and won't block the event loop meaningfully.
"""

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

    Thread-safe implementation for concurrent access.
    """

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        self.config = config or RateLimitConfig()
        self._state: dict[str, RateLimitState] = defaultdict(RateLimitState)
        self._lock = Lock()

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """Check if request is allowed for the given key.

        Returns:
            Tuple of (is_allowed, retry_after_seconds)
        """
        now = time.time()

        with self._lock:
            state = self._state[key]

            # Check if currently blocked
            if state.blocked_until > now:
                return False, int(state.blocked_until - now)

            # Clean old requests outside window
            window_start = now - self.config.window_seconds
            state.requests = [ts for ts in state.requests if ts > window_start]

            # Check rate limit
            if len(state.requests) >= self.config.max_requests:
                # Block the key
                state.blocked_until = now + self.config.block_seconds
                return False, self.config.block_seconds

            # Allow request
            state.requests.append(now)
            return True, 0

    def reset(self, key: str) -> None:
        """Reset rate limit state for a key (e.g., after successful login)."""
        with self._lock:
            if key in self._state:
                del self._state[key]


# Global rate limiters for auth endpoints
auth_rate_limiter = RateLimiter(
    RateLimitConfig(
        max_requests=5,  # 5 attempts
        window_seconds=60,  # per minute
        block_seconds=300,  # 5 minute block
    )
)

register_rate_limiter = RateLimiter(
    RateLimitConfig(
        max_requests=3,  # 3 registrations
        window_seconds=3600,  # per hour
        block_seconds=3600,  # 1 hour block
    )
)
