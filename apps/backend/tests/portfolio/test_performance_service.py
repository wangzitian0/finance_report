"""Tests for portfolio performance service (XIRR, TWR, MWR)."""

import pytest
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.services.performance import (
    calculate_xirr,
    calculate_time_weighted_return,
    calculate_money_weighted_return,
    InsufficientDataError,
)


@pytest.mark.asyncio
async def test_xirr_insufficient_data(db: AsyncSession, test_user):
    with pytest.raises(InsufficientDataError):
        await calculate_xirr(db, test_user.id)


@pytest.mark.asyncio
async def test_time_weighted_return_empty_portfolio(db: AsyncSession, test_user):
    start = date.today() - timedelta(days=30)
    end = date.today()

    twr = await calculate_time_weighted_return(db, test_user.id, start, end)
    assert twr == Decimal("0")


@pytest.mark.asyncio
async def test_money_weighted_return_insufficient_data(db: AsyncSession, test_user):
    with pytest.raises(InsufficientDataError):
        await calculate_money_weighted_return(db, test_user.id)
