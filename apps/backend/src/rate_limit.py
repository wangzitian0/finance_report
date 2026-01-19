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

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock

import redis

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Rate limit configuration."""

    max_requests: int = 5  # Maximum requests in window
    window_seconds: int = 60  # Time window in seconds
    block_seconds: int = 300  # Block duration after exceeding limit


@dataclass
class RateLimitState:
    """State for a single IP/key (in-memory fallback)."""

    requests: list[float] = field(default_factory=list)
    blocked_until: float = 0.0


class RateLimiter:
    """Rate limiter with Redis support and in-memory fallback.

    Uses sliding window algorithm. Thread-safe for concurrent access.
    """

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        self.config = config or RateLimitConfig()
        self._local_state: dict[str, RateLimitState] = defaultdict(RateLimitState)
        self._lock = Lock()
        self._redis: redis.Redis | None = None

        if settings.redis_url:
            try:
                self._redis = redis.from_url(settings.redis_url, decode_responses=True)
                self._redis.ping()
            except Exception:
                # Fallback to local memory if Redis connection fails
                self._redis = None

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """Check if request is allowed for the given key."""
        if self._redis:
            return self._is_allowed_redis(key)
        return self._is_allowed_local(key)

    def _is_allowed_redis(self, key: str) -> tuple[bool, int]:
        """Redis-based rate limiting using a sorted set for sliding window."""
        now = time.time()
        # Namespace keys to avoid collisions
        rl_key = f"rl:{key}"
        block_key = f"rl_block:{key}"

        try:
            # Check if blocked
            blocked_until = self._redis.get(block_key)
            if blocked_until:
                remaining = int(float(blocked_until) - now)
                if remaining > 0:
                    return False, remaining

            # Add current request and prune old ones
            pipe = self._redis.pipeline()
            pipe.zadd(rl_key, {str(now): now})
            pipe.zremrangebyscore(rl_key, 0, now - self.config.window_seconds)
            pipe.zcard(rl_key)
            pipe.expire(rl_key, self.config.window_seconds * 2)
            results = pipe.execute()

            request_count = results[2]

            if request_count >= self.config.max_requests:
                # Block the key
                block_val = str(now + self.config.block_seconds)
                self._redis.setex(block_key, self.config.block_seconds, block_val)
                return False, self.config.block_seconds

            return True, 0
        except Exception as exc:
            logger.warning("Redis error during rate limiting, falling back to local: %s", exc)
            return self._is_allowed_local(key)

    def _is_allowed_local(self, key: str) -> tuple[bool, int]:
        """Local memory fallback for rate limiting."""
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
        if self._redis:
            try:
                self._redis.delete(f"rl:{key}", f"rl_block:{key}")
            except Exception as exc:
                logger.warning("Redis error during reset, ignoring: %s", exc)
        
        with self._lock:
            if key in self._local_state:
                del self._local_state[key]

    def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            self._redis.close()


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
