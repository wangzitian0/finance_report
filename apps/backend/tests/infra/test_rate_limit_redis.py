"""Tests for Redis-based rate limiting functionality."""

from unittest.mock import MagicMock, patch

import pytest

from src.rate_limit import RateLimitConfig, RateLimiter

# Mock settings to have a redis_url
MOCK_SETTINGS = MagicMock()
MOCK_SETTINGS.redis_url = "redis://localhost:6379/0"


@pytest.fixture
def mock_redis():
    """Mock the redis client."""
    with patch("src.rate_limit.redis.from_url") as mock_from_url:
        mock_client = MagicMock()
        mock_from_url.return_value = mock_client

        # Mock pipeline
        mock_pipeline = MagicMock()
        mock_client.pipeline.return_value = mock_pipeline

        # Default pipeline execution result: [zadd_res, zrem_res, zcard_res (count), expire_res]
        # zcard_res (index 2) is the count of requests
        mock_pipeline.execute.return_value = [1, 0, 1, True]

        yield mock_client


@pytest.fixture
def limiter_with_redis(mock_redis):
    """Create a RateLimiter with mocked Redis."""
    with patch("src.rate_limit.settings", MOCK_SETTINGS):
        limiter = RateLimiter(RateLimitConfig(max_requests=5, window_seconds=60, block_seconds=300))
        return limiter


def test_init_with_redis(mock_redis):
    """Test initialization with Redis available."""
    with patch("src.rate_limit.settings", MOCK_SETTINGS):
        limiter = RateLimiter()
        assert limiter._redis is not None
        mock_redis.ping.assert_called_once()


def test_redis_init_failure():
    """Test initialization fallback when Redis connection fails."""
    with patch("src.rate_limit.settings", MOCK_SETTINGS):
        with patch("src.rate_limit.redis.from_url") as mock_from_url:
            mock_from_url.side_effect = Exception("Connection error")
            limiter = RateLimiter()
            assert limiter._redis is None


def test_is_allowed_redis_success(limiter_with_redis, mock_redis):
    """Test allowed request via Redis."""
    # Setup mock to return no existing block
    mock_redis.get.return_value = None

    # Setup pipeline to return count=1 (less than max=5)
    mock_pipeline = mock_redis.pipeline.return_value
    mock_pipeline.execute.return_value = [1, 0, 1, True]

    allowed, retry = limiter_with_redis.is_allowed("test-key")

    assert allowed is True
    assert retry == 0

    # Verify Redis calls
    mock_redis.get.assert_called_with("rl_block:test-key")
    mock_pipeline.zadd.assert_called()
    mock_pipeline.expire.assert_called()
    mock_pipeline.execute.assert_called()


def test_is_allowed_redis_blocked_existing(limiter_with_redis, mock_redis):
    """Test request blocked by existing Redis block key."""
    # Setup mock to return a future timestamp for block
    import time

    future_time = time.time() + 100
    mock_redis.get.return_value = str(future_time)

    allowed, retry = limiter_with_redis.is_allowed("test-key")

    assert allowed is False
    assert 99 <= retry <= 100

    # Should not attempt to increment count if already blocked
    mock_redis.pipeline.assert_not_called()


def test_is_allowed_redis_exceeds_limit(limiter_with_redis, mock_redis):
    """Test request triggering a new block in Redis."""
    # No existing block
    mock_redis.get.return_value = None

    # Pipeline returns count=5 (equal to max=5)
    mock_pipeline = mock_redis.pipeline.return_value
    mock_pipeline.execute.return_value = [1, 0, 5, True]

    allowed, retry = limiter_with_redis.is_allowed("test-key")

    assert allowed is False
    assert retry == 300  # block_seconds

    # Verify block was set
    mock_redis.setex.assert_called()
    args = mock_redis.setex.call_args
    assert args[0][0] == "rl_block:test-key"
    assert args[0][1] == 300


def test_is_allowed_redis_error_fallback(limiter_with_redis, mock_redis):
    """Test fallback to local when Redis operation fails."""
    # Mock Redis get to raise exception
    mock_redis.get.side_effect = Exception("Redis down")

    # Should fallback to local, which is empty, so allowed
    allowed, retry = limiter_with_redis.is_allowed("test-key")

    assert allowed is True
    assert retry == 0


def test_reset_redis(limiter_with_redis, mock_redis):
    """Test reset clears Redis keys."""
    limiter_with_redis.reset("test-key")

    mock_redis.delete.assert_called_with("rl:test-key", "rl_block:test-key")


def test_reset_redis_error(limiter_with_redis, mock_redis):
    """Test reset handles Redis errors gracefully."""
    mock_redis.delete.side_effect = Exception("Redis error")

    # Should not raise
    limiter_with_redis.reset("test-key")


def test_close_redis(limiter_with_redis, mock_redis):
    """Test closing Redis connection."""
    limiter_with_redis.close()
    mock_redis.close.assert_called_once()
