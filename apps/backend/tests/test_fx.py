"""Tests for FX rate service."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import FxRate
from src.services import fx as fx_service
from src.services.fx import convert_amount, get_average_rate, get_exchange_rate


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
