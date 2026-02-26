"""Tests for portfolio allocation service."""

import pytest
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.layer2 import AssetType
from src.models.layer3 import ManagedPosition, PositionStatus, CostBasisMethod
from src.models.account import Account, AccountType
from src.services.allocation import (
    get_sector_allocation,
    get_geography_allocation,
    get_asset_class_allocation,
)


@pytest.fixture
async def investment_account(db: AsyncSession, test_user):
    account = Account(
        user_id=test_user.id,
        name="Investment Account",
        type=AccountType.ASSET,
        currency="USD",
    )
    db.add(account)
    await db.flush()
    return account


@pytest.fixture
async def tech_stock_position(db: AsyncSession, test_user, investment_account):
    position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment_account.id,
        asset_identifier="AAPL",
        quantity=Decimal("100"),
        cost_basis=Decimal("15000.00"),
        currency="USD",
        acquisition_date=date(2023, 1, 1),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(position)
    await db.flush()
    return position


@pytest.fixture
async def finance_stock_position(db: AsyncSession, test_user, investment_account):
    position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment_account.id,
        asset_identifier="JPM",
        quantity=Decimal("50"),
        cost_basis=Decimal("7500.00"),
        currency="USD",
        acquisition_date=date(2023, 6, 1),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(position)
    await db.flush()
    return position


@pytest.mark.asyncio
async def test_sector_allocation_empty_portfolio(db: AsyncSession, test_user):
    result = await get_sector_allocation(db, test_user.id)
    assert result == []


@pytest.mark.asyncio
async def test_geography_allocation_empty_portfolio(db: AsyncSession, test_user):
    result = await get_geography_allocation(db, test_user.id)
    assert result == []


@pytest.mark.asyncio
async def test_asset_class_allocation_empty_portfolio(db: AsyncSession, test_user):
    result = await get_asset_class_allocation(db, test_user.id)
    assert result == []


@pytest.mark.asyncio
async def test_sector_allocation_with_positions(
    db: AsyncSession, test_user, tech_stock_position, finance_stock_position
):
    result = await get_sector_allocation(db, test_user.id)

    assert len(result) > 0
    assert all(hasattr(item, "category") for item in result)
    assert all(hasattr(item, "value") for item in result)
    assert all(hasattr(item, "percentage") for item in result)
    assert all(hasattr(item, "count") for item in result)


@pytest.mark.asyncio
async def test_geography_allocation_with_positions(
    db: AsyncSession, test_user, tech_stock_position, finance_stock_position
):
    result = await get_geography_allocation(db, test_user.id)

    assert len(result) > 0
    assert all(hasattr(item, "category") for item in result)


@pytest.mark.asyncio
async def test_asset_class_allocation_with_positions(
    db: AsyncSession, test_user, tech_stock_position, finance_stock_position
):
    result = await get_asset_class_allocation(db, test_user.id)

    assert len(result) > 0
    assert all(hasattr(item, "category") for item in result)
