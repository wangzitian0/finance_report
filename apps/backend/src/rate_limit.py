"""Rate limiting for authentication endpoints.

SECURITY: Protects against brute-force attacks on /login and /register endpoints.

The generic rate-limiter machinery (:class:`RateLimiter`, :class:`RateLimitConfig`,
:class:`RateLimitState`) and the app-wide ``api_rate_limiter`` now live in the
``platform`` package — request rate-limiting is cross-cutting runtime middleware,
so it belongs in ``platform/extension``. This module keeps only identity's
auth-specific limiter instances (owned by #1428), constructed from the platform
package's published :class:`RateLimiter` / :class:`RateLimitConfig`.
"""

from __future__ import annotations

from src.config import settings
from src.platform import RateLimitConfig, RateLimiter

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
