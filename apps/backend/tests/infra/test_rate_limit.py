"""Tests for rate limiting functionality."""

import uuid

import pytest
from httpx import AsyncClient
from unittest.mock import patch

from src.rate_limit import RateLimitConfig, RateLimiter


def _unique_key() -> str:
    """Generate a unique key per test run to avoid state bleed between runs."""
    return f"test-{uuid.uuid4().hex}"


def test_rate_limiter_allows_requests_within_limit() -> None:
    """Requests within limit should be allowed."""
    limiter = RateLimiter(RateLimitConfig(max_requests=3, window_seconds=60, block_seconds=300))
    key = _unique_key()

    for _ in range(3):
        allowed, retry_after = limiter.is_allowed(key)
        assert allowed is True
        assert retry_after == 0

    limiter.reset(key)


def test_rate_limiter_blocks_after_limit() -> None:
    """Requests exceeding limit should be blocked."""
    limiter = RateLimiter(RateLimitConfig(max_requests=2, window_seconds=60, block_seconds=10))
    key = _unique_key()

    # First 2 requests allowed
    assert limiter.is_allowed(key)[0] is True
    assert limiter.is_allowed(key)[0] is True

    # Third request should be blocked
    allowed, retry_after = limiter.is_allowed(key)
    assert allowed is False
    assert retry_after > 0

    limiter.reset(key)


def test_rate_limiter_different_keys_independent() -> None:
    """Different keys should have independent rate limits."""
    limiter = RateLimiter(RateLimitConfig(max_requests=1, window_seconds=60, block_seconds=300))
    key1 = _unique_key()
    key2 = _unique_key()

    # First IP exhausts limit
    assert limiter.is_allowed(key1)[0] is True
    assert limiter.is_allowed(key1)[0] is False

    # Second IP still has quota
    assert limiter.is_allowed(key2)[0] is True

    limiter.reset(key1)
    limiter.reset(key2)


def test_rate_limiter_reset_clears_state() -> None:
    """Reset should clear rate limit state for a key."""
    limiter = RateLimiter(RateLimitConfig(max_requests=1, window_seconds=60, block_seconds=300))
    key = _unique_key()

    # Exhaust limit
    assert limiter.is_allowed(key)[0] is True
    assert limiter.is_allowed(key)[0] is False

    # Reset should allow new requests
    limiter.reset(key)
    assert limiter.is_allowed(key)[0] is True

    limiter.reset(key)


def test_rate_limiter_returns_remaining_block_time() -> None:
    """Blocked requests should return remaining block time on subsequent attempts."""
    limiter = RateLimiter(RateLimitConfig(max_requests=1, window_seconds=60, block_seconds=100))
    key = _unique_key()

    # First request allowed
    assert limiter.is_allowed(key)[0] is True

    # Second request triggers block
    allowed, retry_after = limiter.is_allowed(key)
    assert allowed is False
    assert retry_after == 100  # Full block duration on first block

    # Third request while still blocked should return remaining time
    allowed, retry_after = limiter.is_allowed(key)
    assert allowed is False
    assert 0 < retry_after <= 100  # Remaining time

    limiter.reset(key)


def test_rate_limiter_reset_nonexistent_key_is_safe() -> None:
    """Reset on a key that doesn't exist should not raise."""
    limiter = RateLimiter(RateLimitConfig(max_requests=5, window_seconds=60, block_seconds=300))
    # Should not raise
    limiter.reset(_unique_key())


@pytest.mark.asyncio
async def test_global_rate_limit_middleware_exempts_health(public_client: AsyncClient) -> None:
    """/health should never be rate-limited."""
    from src.rate_limit import api_rate_limiter

    with patch.object(api_rate_limiter, "is_allowed", return_value=(False, 30)):
        for _ in range(3):
            response = await public_client.get("/health")
            assert response.status_code != 429


@pytest.mark.asyncio
async def test_global_rate_limit_middleware_blocks_after_limit(public_client: AsyncClient) -> None:
    """After exceeding limit, middleware returns 429 with Retry-After header."""
    from src.rate_limit import api_rate_limiter

    # Use a non-exempt path (not in _RATE_LIMIT_EXEMPT_PATHS)
    with patch.object(api_rate_limiter, "is_allowed", return_value=(False, 30)):
        response = await public_client.post("/auth/login", json={"email": "x@x.com", "password": "x"})
        assert response.status_code == 429
        assert "Retry-After" in response.headers
        data = response.json()
        assert "Rate limit exceeded" in data["detail"]


@pytest.mark.asyncio
async def test_global_rate_limit_middleware_allows_normal_requests(public_client: AsyncClient) -> None:
    """Normal requests within limit should pass through (non-exempt path, limiter called)."""
    from src.rate_limit import api_rate_limiter

    # Use a non-exempt path so the middleware actually invokes the rate limiter.
    with patch.object(api_rate_limiter, "is_allowed", return_value=(True, 0)) as mock_is_allowed:
        response = await public_client.post("/auth/login", json={"email": "x@x.com", "password": "x"})
        # Whatever auth returns (e.g. 401), it must NOT be a 429 when allowed.
        assert response.status_code != 429
        # Middleware must have consulted the rate limiter.
        assert mock_is_allowed.called


@pytest.mark.asyncio
async def test_global_rate_limit_middleware_exempts_docs(public_client: AsyncClient) -> None:
    """/docs should never be rate-limited."""
    from src.rate_limit import api_rate_limiter

    with patch.object(api_rate_limiter, "is_allowed", return_value=(False, 30)):
        response = await public_client.get("/docs")
        # docs may redirect or return 200, but NOT 429
        assert response.status_code != 429
