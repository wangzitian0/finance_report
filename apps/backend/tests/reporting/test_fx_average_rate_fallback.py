"""Tests for FX rate service - average rate fallback warning and related behaviour."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.pricing.orm.market_data import FxRate
from src.services.fx import FxRateError, _CacheEntry, _FxRateCache, clear_fx_cache, get_average_rate


async def test_get_average_rate_returns_average_when_rates_exist(db: AsyncSession):
    """get_average_rate should return the SQL average of rates in the period."""
    rates = [
        FxRate(
            base_currency="USD", quote_currency="SGD", rate=Decimal("1.20"), rate_date=date(2025, 1, 1), source="test"
        ),
        FxRate(
            base_currency="USD", quote_currency="SGD", rate=Decimal("1.40"), rate_date=date(2025, 1, 31), source="test"
        ),
    ]
    db.add_all(rates)
    await db.commit()

    clear_fx_cache()
    result = await get_average_rate(db, "USD", "SGD", date(2025, 1, 1), date(2025, 1, 31))

    assert result == Decimal("1.30"), f"Expected 1.30, got {result}"


async def test_get_average_rate_logs_warning_on_fallback(db: AsyncSession):
    """When no rates exist in period, get_average_rate logs a warning before falling back."""
    # Add a rate outside the requested period so the fallback (spot) query finds something
    db.add(
        FxRate(
            base_currency="EUR", quote_currency="SGD", rate=Decimal("1.50"), rate_date=date(2024, 12, 31), source="test"
        )
    )
    await db.commit()

    clear_fx_cache()

    with patch("src.services.fx.logger") as mock_logger:
        result = await get_average_rate(db, "EUR", "SGD", date(2025, 1, 1), date(2025, 1, 31))

    # Should log a warning about the fallback
    mock_logger.warning.assert_called_once()
    call_kwargs = mock_logger.warning.call_args
    # First positional arg is the message
    message = call_kwargs[0][0]
    assert "fallback" in message.lower() or "spot" in message.lower(), (
        f"Warning message should mention fallback or spot rate, got: {message!r}"
    )

    # Should still return a usable rate (the spot rate fallback)
    assert result == Decimal("1.50")


async def test_get_average_rate_no_warning_when_rates_present(db: AsyncSession):
    """When rates exist in the period, no warning should be logged."""
    db.add(
        FxRate(
            base_currency="USD", quote_currency="SGD", rate=Decimal("1.30"), rate_date=date(2025, 2, 15), source="test"
        )
    )
    await db.commit()

    clear_fx_cache()

    with patch("src.services.fx.logger") as mock_logger:
        await get_average_rate(db, "USD", "SGD", date(2025, 2, 1), date(2025, 2, 28))

    mock_logger.warning.assert_not_called()


async def test_get_average_rate_raises_when_no_rate_at_all(db: AsyncSession):
    """When no rate exists anywhere (including as a spot fallback), FxRateError is raised."""
    # No rates in DB at all for this pair
    clear_fx_cache()

    with pytest.raises(FxRateError):
        await get_average_rate(db, "XYZ", "SGD", date(2025, 1, 1), date(2025, 1, 31))


async def test_get_average_rate_same_currency_returns_one(db: AsyncSession):
    """Same base and quote currency should return 1.0 without any DB query."""
    clear_fx_cache()
    result = await get_average_rate(db, "SGD", "SGD", date(2025, 1, 1), date(2025, 1, 31))
    assert result == Decimal("1")


def test_fx_warning_cache_drops_expired_warning():
    """Expired cached average-rate warnings are removed instead of being reused."""
    cache = _FxRateCache()
    cache._store["fx:USD:SGD:2025-01-01:2025-01-31"] = _CacheEntry(
        value=Decimal("1.35"),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        warning={"type": "average_rate_fallback"},
    )

    warning = cache.get_warning("fx:USD:SGD:2025-01-01:2025-01-31")

    assert warning is None
    assert cache._store == {}
