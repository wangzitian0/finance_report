"""Tests for rate limiting functionality."""

from src.rate_limit import RateLimitConfig, RateLimiter


def test_rate_limiter_allows_requests_within_limit() -> None:
    """Requests within limit should be allowed."""
    limiter = RateLimiter(RateLimitConfig(max_requests=3, window_seconds=60, block_seconds=300))

    for _ in range(3):
        allowed, retry_after = limiter.is_allowed("test-ip")
        assert allowed is True
        assert retry_after == 0


def test_rate_limiter_blocks_after_limit() -> None:
    """Requests exceeding limit should be blocked."""
    limiter = RateLimiter(RateLimitConfig(max_requests=2, window_seconds=60, block_seconds=10))

    # First 2 requests allowed
    assert limiter.is_allowed("test-ip")[0] is True
    assert limiter.is_allowed("test-ip")[0] is True

    # Third request should be blocked
    allowed, retry_after = limiter.is_allowed("test-ip")
    assert allowed is False
    assert retry_after > 0


def test_rate_limiter_different_keys_independent() -> None:
    """Different keys should have independent rate limits."""
    limiter = RateLimiter(RateLimitConfig(max_requests=1, window_seconds=60, block_seconds=300))

    # First IP exhausts limit
    assert limiter.is_allowed("ip-1")[0] is True
    assert limiter.is_allowed("ip-1")[0] is False

    # Second IP still has quota
    assert limiter.is_allowed("ip-2")[0] is True


def test_rate_limiter_reset_clears_state() -> None:
    """Reset should clear rate limit state for a key."""
    limiter = RateLimiter(RateLimitConfig(max_requests=1, window_seconds=60, block_seconds=300))

    # Exhaust limit
    assert limiter.is_allowed("test-ip")[0] is True
    assert limiter.is_allowed("test-ip")[0] is False

    # Reset should allow new requests
    limiter.reset("test-ip")
    assert limiter.is_allowed("test-ip")[0] is True


def test_rate_limiter_returns_remaining_block_time() -> None:
    """Blocked requests should return remaining block time on subsequent attempts."""
    limiter = RateLimiter(RateLimitConfig(max_requests=1, window_seconds=60, block_seconds=100))

    # First request allowed
    assert limiter.is_allowed("test-ip")[0] is True

    # Second request triggers block
    allowed, retry_after = limiter.is_allowed("test-ip")
    assert allowed is False
    assert retry_after == 100  # Full block duration on first block

    # Third request while still blocked should return remaining time
    allowed, retry_after = limiter.is_allowed("test-ip")
    assert allowed is False
    assert 0 < retry_after <= 100  # Remaining time


def test_rate_limiter_reset_nonexistent_key_is_safe() -> None:
    """Reset on a key that doesn't exist should not raise."""
    limiter = RateLimiter(RateLimitConfig(max_requests=5, window_seconds=60, block_seconds=300))
    # Should not raise
    limiter.reset("nonexistent-key")
