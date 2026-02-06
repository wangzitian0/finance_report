import pytest
from datetime import timedelta, datetime, UTC
from decimal import Decimal
from unittest.mock import patch, MagicMock

from src.services.fx import _FxRateCache, clear_fx_cache, _cache


@pytest.fixture
def db_engine():
    """Mock db_engine to avoid DB connection in unit tests."""
    return MagicMock()


class TestFxRateCache:
    def test_cache_set_get(self):
        """Test basic set and get functionality."""
        cache = _FxRateCache()
        cache.set("key1", Decimal("1.5"))
        assert cache.get("key1") == Decimal("1.5")
        assert cache.get("key2") is None

    def test_cache_expiry(self):
        """Test that keys expire after TTL."""
        # Create cache with 1 second TTL
        cache = _FxRateCache(ttl_seconds=1)
        cache.set("key1", Decimal("1.5"))

        # Verify it's there
        assert cache.get("key1") == Decimal("1.5")

        # Mock datetime to be 2 seconds later
        future = datetime.now(UTC) + timedelta(seconds=2)
        with patch("src.services.fx.datetime") as mock_datetime:
            mock_datetime.now.return_value = future
            mock_datetime.UTC = UTC

            # Should be expired
            assert cache.get("key1") is None

    def test_cache_eviction(self):
        """Test cache eviction policy."""
        # Use larger size to ensure eviction calc > 0
        cache = _FxRateCache(max_size=10)
        for i in range(10):
            cache.set(f"k{i}", Decimal(i))

        assert len(cache._store) == 10

        # Add 11th item
        cache.set("k10", Decimal("10"))

        # Should trigger eviction logic
        # 10 * 0.2 = 2 items removed.
        # Total items: 10 (initial) - 2 (evicted) + 1 (new) = 9
        # Or if it cleans expired first (none here), then hard limit.

        # Logic:
        # if len >= max:
        #   remove expired
        #   if len >= max:
        #     remove 20%

        # So: 10 >= 10. No expired. 10 >= 10. Remove 2. Remaining 8.
        # Add new. Total 9.
        assert len(cache._store) < 11
        assert "k10" in cache._store

    def test_clear_fx_cache(self):
        """Test clearing the global cache."""
        _cache.set("test_global", Decimal("1"))
        assert _cache.get("test_global") == Decimal("1")
        clear_fx_cache()
        assert _cache.get("test_global") is None
