"""Rate limiting for authentication endpoints.

SECURITY: Protects against brute-force attacks on /login and /register endpoints.
Uses in-memory storage with sliding window algorithm.

NOTE: This implementation uses in-memory, per-process storage. In a multi-instance
deployment (e.g., multiple workers/containers behind a load balancer), each instance
maintains its own counters, effectively multiplying the allowed requests by the
number of instances. For single-instance deployment this is sufficient.

Threading note: We use threading.Lock rather than asyncio.Lock because the critical
section is very short (dict operations only). This is acceptable for FastAPI/uvicorn
as the lock is held for microseconds and won't block the event loop meaningfully.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock

from src.config import settings
from src.logger import get_logger

logger = get_logger(__name__)


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
                return False, int(state.blocked_until - now)

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
        max_requests=settings.register_rate_limit_requests,  # default: 10 registrations
        window_seconds=settings.register_rate_limit_window,  # default: per 600s
        block_seconds=600,  # 10 minute block
    )
)


# Global rate limiter for all API endpoints (excluding health/docs/metrics)
api_rate_limiter = RateLimiter(
    RateLimitConfig(
        max_requests=settings.api_rate_limit_requests,  # default: 100 req
        window_seconds=settings.api_rate_limit_window,  # default: per 60s
        block_seconds=60,  # 1 minute block
    )
)
