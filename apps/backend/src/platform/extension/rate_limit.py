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

import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from starlette.requests import Request

logger = logging.getLogger(__name__)
DEFAULT_MAX_LOCAL_KEYS = 10_000

_REDIS_SLIDING_WINDOW_LUA = """
local block_ttl = redis.call('TTL', KEYS[2])
if block_ttl > 0 then
    return {0, block_ttl}
end
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local max_requests = tonumber(ARGV[3])
local block_seconds = tonumber(ARGV[4])
local member = ARGV[5]
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now_ms - window_ms)
local count = redis.call('ZCARD', KEYS[1])
if count >= max_requests then
    redis.call('SET', KEYS[2], '1', 'EX', block_seconds)
    return {0, block_seconds}
end
redis.call('ZADD', KEYS[1], now_ms, member)
redis.call('PEXPIRE', KEYS[1], window_ms)
return {1, 0}
"""


def get_client_ip(request: Request, *, trust_proxy: bool | None = None) -> str:
    """Extract client IP from request, honoring the rightmost X-Forwarded-For entry when trusted.

    When ``trust_proxy`` is True (or ``src.config.settings.trust_proxy`` when not explicitly passed),
    the rightmost non-empty address in ``X-Forwarded-For`` is used — the address appended by the
    nearest trusted reverse proxy — preventing a client from spoofing a left-hand XFF entry to
    bypass rate limits (#2674).
    """
    if trust_proxy is None:
        import src.config

        trust_proxy = bool(src.config.settings.trust_proxy)
    if trust_proxy:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            parts = [part.strip() for part in forwarded.split(",") if part.strip()]
            if parts:
                return parts[-1]
    return request.client.host if request.client else "unknown"


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
    """Sliding-window rate limiter with Redis backend and bounded in-memory fallback.

    Thread-safe for concurrent access.
    """

    def __init__(
        self,
        config: RateLimitConfig | None = None,
        *,
        namespace: str = "default",
        redis_url: str | None = None,
        max_keys: int = DEFAULT_MAX_LOCAL_KEYS,
    ) -> None:
        self.config = config or RateLimitConfig()
        self._namespace = namespace
        self._redis_url = redis_url or None
        self._max_keys = max(1, max_keys)
        self._local_state: dict[str, RateLimitState] = {}
        self._lock = Lock()
        self._last_prune = 0.0
        self._redis_clients: dict[str, Any] = {}

    def _prune_expired_locked(self, now: float) -> None:
        window_start = now - self.config.window_seconds
        expired = [
            k
            for k, state in self._local_state.items()
            if state.blocked_until <= now and not any(ts >= window_start for ts in state.requests)
        ]
        for k in expired:
            del self._local_state[k]
        self._last_prune = now

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """Check if request is allowed for the given key."""
        now = time.time()
        window_start = now - self.config.window_seconds
        with self._lock:
            state = self._local_state.get(key)
            if state is None:
                if len(self._local_state) >= self._max_keys or (
                    self._local_state and now - self._last_prune >= max(self.config.window_seconds, 1.0)
                ):
                    self._prune_expired_locked(now)
                while len(self._local_state) >= self._max_keys:
                    oldest_key = next(iter(self._local_state))
                    del self._local_state[oldest_key]
                state = RateLimitState()
                self._local_state[key] = state
            elif state.blocked_until > now:
                return False, max(1, math.ceil(state.blocked_until - now))

            state.requests = [ts for ts in state.requests if ts >= window_start]

            if len(state.requests) >= self.config.max_requests:
                state.blocked_until = now + self.config.block_seconds
                return False, self.config.block_seconds

            state.requests.append(now)
            return True, 0

    def _redis_keys(self, key: str) -> tuple[str, str]:
        prefix = f"rl:{self._namespace}:{key}"
        return f"{prefix}:w", f"{prefix}:b"

    def _get_async_redis_client(self, redis_url: str) -> Any:
        client = self._redis_clients.get(redis_url)
        if client is None:
            import redis.asyncio

            client = redis.asyncio.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
            )
            self._redis_clients[redis_url] = client
        return client

    async def is_allowed_async(self, key: str) -> tuple[bool, int]:
        """Check rate limit via Redis when configured, falling back to local memory."""
        if not self._redis_url:
            return self.is_allowed(key)
        window_key, block_key = self._redis_keys(key)
        now_ms = int(time.time() * 1000)
        window_ms = max(1, int(self.config.window_seconds * 1000))
        member = f"{now_ms}:{uuid.uuid4().hex}"
        try:
            client = self._get_async_redis_client(self._redis_url)
            res = await client.eval(
                _REDIS_SLIDING_WINDOW_LUA,
                2,
                window_key,
                block_key,
                now_ms,
                window_ms,
                self.config.max_requests,
                self.config.block_seconds,
                member,
            )
            allowed_flag, retry_after = int(res[0]), int(res[1])
            return bool(allowed_flag), retry_after
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "RateLimiter Redis backend unavailable for namespace=%s error=%s; falling back to local memory",
                self._namespace,
                type(exc).__name__,
            )
            return self.is_allowed(key)

    def reset(self, key: str) -> None:
        """Reset rate limit state for a key."""
        with self._lock:
            if key in self._local_state:
                del self._local_state[key]

    async def reset_async(self, key: str) -> None:
        """Reset rate limit state in local memory and Redis when configured."""
        self.reset(key)
        if not self._redis_url:
            return
        window_key, block_key = self._redis_keys(key)
        try:
            client = self._get_async_redis_client(self._redis_url)
            await client.delete(window_key, block_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "RateLimiter Redis reset failed for namespace=%s error=%s",
                self._namespace,
                type(exc).__name__,
            )

    def clear(self) -> None:
        """Drop all rate-limit state (every key). Used for test isolation."""
        with self._lock:
            self._local_state.clear()

    async def clear_async(self) -> None:
        """Drop local and Redis keys for this namespace and close Redis clients."""
        self.clear()
        if not self._redis_url:
            return
        try:
            client = self._get_async_redis_client(self._redis_url)
            if hasattr(client, "scan_iter"):
                keys = [k async for k in client.scan_iter(match=f"rl:{self._namespace}:*")]
                if keys:
                    await client.delete(*keys)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "RateLimiter Redis clear failed for namespace=%s error=%s",
                self._namespace,
                type(exc).__name__,
            )
        finally:
            for client in list(self._redis_clients.values()):
                try:
                    await client.aclose()
                except Exception:  # noqa: BLE001
                    pass
            self._redis_clients.clear()
