"""Tests for FX rate service."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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

    result = await get_average_rate(
        DummySession(), "USD", "SGD", date(2025, 1, 1), date(2025, 1, 2)
    )
    assert result == Decimal("1.11")
