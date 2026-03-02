from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.fx import FxRateError, PrefetchedFxRates, _cache, _FxRateCache, clear_fx_cache


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


class TestPrefetchedFxRates:
    @pytest.mark.asyncio
    async def test_prefetch_propagates_fx_rate_error(self):
        prefetched = PrefetchedFxRates()

        with patch("src.services.fx.get_exchange_rate", new_callable=AsyncMock) as mock_get_rate:
            mock_get_rate.side_effect = FxRateError("missing")

            with pytest.raises(FxRateError, match="missing"):
                await prefetched.prefetch(
                    db=MagicMock(),
                    pairs=[("USD", "SGD", datetime.now(UTC).date(), None, None)],
                )


class TestPrefetchedFxRatesNonFxRateError:
    """Test ExceptionGroup re-raise when non-FxRateError (lines 259->258, 261)."""

    @pytest.mark.asyncio
    async def test_prefetch_reraises_non_fx_rate_exception_group(self):
        """AC5.7.1 – ExceptionGroup containing non-FxRateError is re-raised as-is."""
        prefetched = PrefetchedFxRates()

        with patch("src.services.fx.get_exchange_rate", new_callable=AsyncMock) as mock_get_rate:
            mock_get_rate.side_effect = ValueError("unexpected error")

            with pytest.raises((ExceptionGroup, ValueError)):
                await prefetched.prefetch(
                    db=MagicMock(),
                    pairs=[("USD", "SGD", datetime.now(UTC).date(), None, None)],
                )

    @pytest.mark.asyncio
    async def test_prefetch_empty_pairs_returns_immediately(self):
        """AC5.7.2 – Empty pairs list returns without calling get_exchange_rate (line 250 branch)."""
        prefetched = PrefetchedFxRates()

        with patch("src.services.fx.get_exchange_rate", new_callable=AsyncMock) as mock_get_rate:
            await prefetched.prefetch(
                db=MagicMock(),
                pairs=[],
            )
            mock_get_rate.assert_not_called()
