"""Tests for FX rate service - average rate fallback warning and related behaviour."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import FxRate
from src.services.fx import FxRateError, clear_fx_cache, get_average_rate


@pytest.mark.asyncio
async def test_get_average_rate_returns_average_when_rates_exist(db: AsyncSession):
    """get_average_rate should return the SQL average of rates in the period."""
    rates = [
        FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.20"), rate_date=date(2025, 1, 1), source="test"),
        FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.40"), rate_date=date(2025, 1, 31), source="test"),
    ]
    db.add_all(rates)
    await db.commit()

    clear_fx_cache()
    result = await get_average_rate(db, "USD", "SGD", date(2025, 1, 1), date(2025, 1, 31))

    assert result == Decimal("1.30"), f"Expected 1.30, got {result}"


@pytest.mark.asyncio
async def test_get_average_rate_logs_warning_on_fallback(db: AsyncSession):
    """When no rates exist in period, get_average_rate logs a warning before falling back."""
    # Add a rate outside the requested period so the fallback (spot) query finds something
    db.add(FxRate(base_currency="EUR", quote_currency="SGD", rate=Decimal("1.50"), rate_date=date(2024, 12, 31), source="test"))
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


@pytest.mark.asyncio
async def test_get_average_rate_no_warning_when_rates_present(db: AsyncSession):
    """When rates exist in the period, no warning should be logged."""
    db.add(FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.30"), rate_date=date(2025, 2, 15), source="test"))
    await db.commit()

    clear_fx_cache()

    with patch("src.services.fx.logger") as mock_logger:
        await get_average_rate(db, "USD", "SGD", date(2025, 2, 1), date(2025, 2, 28))

    mock_logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_get_average_rate_raises_when_no_rate_at_all(db: AsyncSession):
    """When no rate exists anywhere (including as a spot fallback), FxRateError is raised."""
    # No rates in DB at all for this pair
    clear_fx_cache()

    with pytest.raises(FxRateError):
        await get_average_rate(db, "XYZ", "SGD", date(2025, 1, 1), date(2025, 1, 31))


@pytest.mark.asyncio
async def test_get_average_rate_same_currency_returns_one(db: AsyncSession):
    """Same base and quote currency should return 1.0 without any DB query."""
    clear_fx_cache()
    result = await get_average_rate(db, "SGD", "SGD", date(2025, 1, 1), date(2025, 1, 31))
    assert result == Decimal("1")
