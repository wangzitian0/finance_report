"""Identity auth-endpoint rate limiters (owned by #1428).

SECURITY: Protects against brute-force attacks on /login and /register.

The generic rate-limiter machinery (:class:`RateLimiter`/:class:`RateLimitConfig`)
lives in the ``platform`` package — request rate-limiting is cross-cutting runtime
middleware. This module keeps only identity's auth-specific limiter instances,
constructed from the platform package's published primitives. These were the
pre-migration ``src/rate_limit.py`` instances, moved into the package's single
home (zero residue).
"""

from __future__ import annotations

# Imported by its bare published root (the package-model idiom): ``src.config`` is
# a kernel package; ``settings`` is read via ``src.config.settings`` so the
# cross-domain gate sees only the bare-root import.
import src.config
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
        max_requests=src.config.settings.register_rate_limit_requests,  # default: 10 registrations
        window_seconds=src.config.settings.register_rate_limit_window,  # default: per 600s
        block_seconds=600,  # 10 minute block
    )
)
