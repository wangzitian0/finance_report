"""AC-pricing.manualvaluation.3: Contract tests for manual valuation liquidity classification."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.pricing import (
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    build_manual_valuation_lines,
)
from src.pricing.orm.manual_valuation import ManualValuationSnapshot


@pytest.fixture
def user_id(test_user):
    return test_user.id


async def test_valuation_lines_liquidity_classification_contract(db: AsyncSession, user_id):
    """Verify that manual valuation lines preserve explicit liquidity classification."""
    as_of_date = date(2025, 4, 30)

    # 1. Liquid asset snapshot (e.g. Long-term savings)
    liquid_snapshot = ManualValuationSnapshot(
        user_id=user_id,
        as_of_date=as_of_date,
        source="Fixed Deposit",
        component_type=ManualValuationComponentType.LONG_TERM_SAVINGS,
        liquidity_class=ManualValuationLiquidityClass.LIQUID,
        currency="SGD",
        value=Decimal("50000.00"),
    )

    # 2. Illiquid / Restricted asset snapshot (e.g. Real Estate property value)
    property_snapshot = ManualValuationSnapshot(
        user_id=user_id,
        as_of_date=as_of_date,
        source="Primary Residence",
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        currency="SGD",
        value=Decimal("500000.00"),
    )

    db.add_all([liquid_snapshot, property_snapshot])
    await db.commit()

    # Case A: Full portfolio (include_restricted=True)
    asset_lines, liability_lines = await build_manual_valuation_lines(
        db,
        user_id,
        as_of_date=as_of_date,
        target_currency="SGD",
        include_restricted=True,
    )
    assert len(asset_lines) == 2
    liquidity_map = {line["name"]: line["allocation_liquidity_class"] for line in asset_lines}
    assert liquidity_map["Valuation: Fixed Deposit (long term savings)"] == ManualValuationLiquidityClass.LIQUID.value
    assert (
        liquidity_map["Valuation: Primary Residence (property value)"] == ManualValuationLiquidityClass.ILLIQUID.value
    )

    # Case B: Liquid-only portfolio (include_restricted=False)
    asset_lines_liquid, _ = await build_manual_valuation_lines(
        db,
        user_id,
        as_of_date=as_of_date,
        target_currency="SGD",
        include_restricted=False,
    )
    assert len(asset_lines_liquid) == 1
    assert asset_lines_liquid[0]["name"] == "Valuation: Fixed Deposit (long term savings)"
