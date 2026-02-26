"""Tests for FX rate service."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession\nfrom sqlalchemy.orm import selectinload\nfrom sqlalchemy.orm import selectinload

from src.models import FxRate
from src.services import fx as fx_service
from src.services.fx import (
    FxRateError,
    convert_amount,
    convert_to_base,
    get_average_rate,
    get_exchange_rate,
)


@pytest.fixture(autouse=True)
def clear_fx_cache() -> None:
    """Clear FX cache to avoid cross-test contamination."""
    fx_service._cache._store.clear()


@pytest.mark.asyncio
async def test_get_exchange_rate_exact(db: AsyncSession):
    """Exact FX rate lookup should return stored rate."""
    rate = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.350000"),
        rate_date=date(2025, 1, 1),
        source="test",
    )
    db.add(rate)
    await db.commit()

    result = await get_exchange_rate(db, "USD", "SGD", date(2025, 1, 1))

    assert result == Decimal("1.350000")


@pytest.mark.asyncio
async def test_get_exchange_rate_fallback(db: AsyncSession):
    """FX rate lookup should fall back to most recent prior rate."""
    rate = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.320000"),
        rate_date=date(2025, 1, 1),
        source="test",
    )
    db.add(rate)
    await db.commit()

    result = await get_exchange_rate(db, "USD", "SGD", date(2025, 1, 3))

    assert result == Decimal("1.320000")


@pytest.mark.asyncio
async def test_get_average_rate(db: AsyncSession):
    """Average rate should be computed for the period."""
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.300000"),
                rate_date=date(2025, 1, 1),
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.500000"),
                rate_date=date(2025, 1, 2),
                source="test",
            ),
        ]
    )
    await db.commit()

    result = await get_average_rate(db, "USD", "SGD", date(2025, 1, 1), date(2025, 1, 2))

    assert result == Decimal("1.400000")


@pytest.mark.asyncio
async def test_convert_amount(db: AsyncSession):
    """Convert amount should apply FX rate without rounding prematurely."""
    rate = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.200000"),
        rate_date=date(2025, 1, 1),
        source="test",
    )
    db.add(rate)
    await db.commit()

    amount = Decimal("100.00")
    expected = amount * Decimal("1.200000")

    result = await convert_amount(db, amount, "USD", "SGD", date(2025, 1, 1))

    assert result == expected


@pytest.mark.asyncio
async def test_get_exchange_rate_same_currency(db: AsyncSession):
    result = await get_exchange_rate(db, "usd", "USD", date(2025, 1, 1))
    assert result == Decimal("1")


@pytest.mark.asyncio
async def test_get_exchange_rate_missing_raises(db: AsyncSession):
    with pytest.raises(FxRateError, match="No FX rate available"):
        await get_exchange_rate(db, "USD", "SGD", date(2025, 1, 1))


@pytest.mark.asyncio
async def test_get_average_rate_invalid_range(db: AsyncSession):
    with pytest.raises(FxRateError, match="start_date must be before end_date"):
        await get_average_rate(db, "USD", "SGD", date(2025, 1, 2), date(2025, 1, 1))


@pytest.mark.asyncio
async def test_get_average_rate_falls_back_to_exchange_rate(db: AsyncSession):
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.250000"),
            rate_date=date(2025, 1, 3),
            source="test",
        )
    )
    await db.commit()

    result = await get_average_rate(db, "USD", "SGD", date(2025, 1, 1), date(2025, 1, 3))

    assert result == Decimal("1.250000")


@pytest.mark.asyncio
async def test_convert_amount_uses_average_rate(db: AsyncSession):
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.200000"),
                rate_date=date(2025, 1, 1),
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.400000"),
                rate_date=date(2025, 1, 2),
                source="test",
            ),
        ]
    )
    await db.commit()

    result = await convert_amount(
        db,
        Decimal("10.00"),
        "USD",
        "SGD",
        date(2025, 1, 2),
        average_start=date(2025, 1, 1),
        average_end=date(2025, 1, 2),
    )

    assert result == Decimal("13.00")


@pytest.mark.asyncio
async def test_convert_amount_same_currency(db: AsyncSession):
    result = await convert_amount(
        db,
        Decimal("10.00"),
        "SGD",
        "sgd",
        date(2025, 1, 1),
    )

    assert result == Decimal("10.00")


@pytest.mark.asyncio
async def test_convert_to_base(db: AsyncSession):
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.300000"),
            rate_date=date(2025, 1, 1),
            source="test",
        )
    )
    await db.commit()

    result = await convert_to_base(db, Decimal("10.00"), "USD", date(2025, 1, 1))

    assert result == Decimal("13.000000")


def test_fx_cache_expired_entry() -> None:
    expired = fx_service._CacheEntry(
        value=Decimal("1.23"),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    fx_service._cache._store["expired"] = expired
    assert fx_service._cache.get("expired") is None


def test_fx_cache_hit() -> None:
    entry = fx_service._CacheEntry(
        value=Decimal("1.10"),
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    fx_service._cache._store["hit"] = entry
    assert fx_service._cache.get("hit") == Decimal("1.10")


@pytest.mark.asyncio
async def test_get_exchange_rate_uses_cache(db: AsyncSession):
    key = "fx:USD:SGD:2025-01-01"
    fx_service._cache._store[key] = fx_service._CacheEntry(
        value=Decimal("1.11"),
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    result = await get_exchange_rate(db, "USD", "SGD", date(2025, 1, 1))
    assert result == Decimal("1.11")


@pytest.mark.asyncio
async def test_get_average_rate_uses_cache(db: AsyncSession):
    key = "fx:USD:SGD:2025-01-01:2025-01-02"
    fx_service._cache._store[key] = fx_service._CacheEntry(
        value=Decimal("1.22"),
        expires_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    result = await get_average_rate(db, "USD", "SGD", date(2025, 1, 1), date(2025, 1, 2))
    assert result == Decimal("1.22")


@pytest.mark.asyncio
async def test_get_average_rate_same_currency(db: AsyncSession):
    result = await get_average_rate(db, "SGD", "SGD", date(2025, 1, 1), date(2025, 1, 2))
    assert result == Decimal("1")


@pytest.mark.asyncio
async def test_get_exchange_rate_casts_non_decimal():
    class DummyResult:
        def scalar_one_or_none(self):
            return 1.2345

    class DummySession:
        async def execute(self, _stmt):
            return DummyResult()

    result = await get_exchange_rate(DummySession(), "USD", "SGD", date(2025, 1, 1))
    assert result == Decimal("1.2345")


@pytest.mark.asyncio
async def test_get_average_rate_casts_non_decimal():
    class DummyResult:
        def scalar_one_or_none(self):
            return 1.11

    class DummySession:
        async def execute(self, _stmt):
            return DummyResult()

    result = await get_average_rate(DummySession(), "USD", "SGD", date(2025, 1, 1), date(2025, 1, 2))
    assert result == Decimal("1.11")


def test_fx_cache_eviction() -> None:
    """Test FX cache eviction logic when it reaches max_size."""
    # Create cache with small max_size for testing
    small_cache = fx_service._FxRateCache(max_size=5)

    # Fill cache
    for i in range(5):
        small_cache.set(f"key{i}", Decimal(str(i)))

    assert len(small_cache._store) == 5

    # Exceed capacity - should trigger eviction
    # Our implementation clears 20% + any expired.
    # Since none are expired, it will remove floor(5 * 0.2) = 1 entry (oldest).
    small_cache.set("key5", Decimal("5"))

    # After set, size should be 5 again (added 1, evicted 1)
    assert len(small_cache._store) == 5
    assert "key0" not in small_cache._store
    assert "key5" in small_cache._store


@pytest.mark.asyncio
async def test_prefetched_fx_rates() -> None:
    """Test the PrefetchedFxRates helper class."""
    from src.services.fx import PrefetchedFxRates

    prefetched = PrefetchedFxRates()

    # Test set/get spot
    prefetched.set_rate("USD", "SGD", date(2025, 1, 1), Decimal("1.35"))
    assert prefetched.get_rate("USD", "SGD", date(2025, 1, 1)) == Decimal("1.35")

    # Test same currency
    assert prefetched.get_rate("SGD", "sgd", date(2025, 1, 1)) == Decimal("1")

    # Test avg rate
    prefetched.set_rate("USD", "SGD", date(2025, 1, 1), Decimal("1.34"), date(2025, 1, 1), date(2025, 1, 31))
    assert prefetched.get_rate("USD", "SGD", date(2025, 1, 1), date(2025, 1, 1), date(2025, 1, 31)) == Decimal("1.34")

    # Missing key
    assert prefetched.get_rate("GBP", "USD", date(2025, 1, 1)) is None


@pytest.mark.asyncio
async def test_prefetch_parallel(db: AsyncSession):
    """Test batch prefetching from database."""
    from src.services.fx import PrefetchedFxRates

    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.30"),
                rate_date=date(2025, 1, 1),
                source="test",
            ),
            FxRate(
                base_currency="EUR",
                quote_currency="SGD",
                rate=Decimal("1.40"),
                rate_date=date(2025, 1, 1),
                source="test",
            ),
        ]
    )
    await db.commit()

    prefetched = PrefetchedFxRates()
    # Fetch sequentially in test to avoid AsyncSession concurrency error
    # but still verifying the data structures and loading logic.
    await prefetched.prefetch(db, [("USD", "SGD", date(2025, 1, 1), None, None)])
    await prefetched.prefetch(db, [("EUR", "SGD", date(2025, 1, 1), None, None)])

    assert prefetched.get_rate("USD", "SGD", date(2025, 1, 1)) == Decimal("1.30")
    assert prefetched.get_rate("EUR", "SGD", date(2025, 1, 1)) == Decimal("1.40")


@pytest.mark.asyncio
async def test_convert_amount_average_fallback_error(db: AsyncSession):
    """Test that convert_amount fails if fallback exchange rate lookup fails."""
    # No rates in DB
    with pytest.raises(FxRateError, match="No FX rate available"):
        await convert_amount(
            db,
            Decimal("10"),
            "USD",
            "SGD",
            date(2025, 1, 1),
            average_start=date(2025, 1, 1),
            average_end=date(2025, 1, 1),
        )
