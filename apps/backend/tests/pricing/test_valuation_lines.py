"""AC-pricing.manualvaluation.3: balance-sheet lines from manual valuations.

Absorbed from ``services/reporting/manual_valuation.py`` (#1610 P2): the
manual-valuation report lines are computed by pricing (they read pricing's
``ManualValuationSnapshot`` facts and pricing's own FX conversion); reporting
consumes the published ``build_manual_valuation_lines`` and maps the pricing
error family to its own ``ReportError`` at the boundary.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer3 import ManualValuationComponentType, ManualValuationLiquidityClass
from src.pricing import PricingError, build_manual_valuation_lines, record_manual_valuation
from src.pricing.orm.market_data import FxRate

pytestmark = pytest.mark.asyncio


async def test_AC_pricing_manualvaluation_3_lines_split_convert_and_classify(db: AsyncSession, test_user) -> None:
    """AC-pricing.manualvaluation.3: latest components become sorted
    asset/liability lines with trusted provenance, allocation classes, and
    FX conversion into the target currency."""
    await record_manual_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        as_of=date(2026, 5, 1),
        value=Decimal("1000000.00"),
        currency="USD",
        source="appraisal",
    )
    await record_manual_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType.MORTGAGE_BALANCE,
        liquidity_class=ManualValuationLiquidityClass.LIABILITY,
        as_of=date(2026, 5, 1),
        value=Decimal("400000.00"),
        currency="SGD",
        source="bank",
    )
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.350000"),
            rate_date=date(2026, 5, 31),
            source="test",
        )
    )
    await db.commit()

    asset_lines, liability_lines = await build_manual_valuation_lines(
        db,
        test_user.id,
        as_of_date=date(2026, 5, 31),
        target_currency="SGD",
    )

    assert len(asset_lines) == 1
    assert len(liability_lines) == 1

    asset = asset_lines[0]
    assert asset["type"] == "ASSET"
    assert asset["amount"] == Decimal("1350000.00")
    assert asset["source_currency"] == "USD"
    assert asset["confidence_tier"] == "TRUSTED"
    assert asset["provenance"] == "manual"
    assert asset["allocation_asset_class"] == "real_estate"
    assert asset["allocation_source_type"] == "manual_valuation"
    assert asset["name"] == "Valuation: appraisal (property value)"

    liability = liability_lines[0]
    assert liability["type"] == "LIABILITY"
    assert liability["amount"] == Decimal("400000.00")
    assert liability["allocation_asset_class"] == "real_estate"
    assert liability["allocation_liquidity_class"] == ManualValuationLiquidityClass.LIABILITY.value


async def test_AC_pricing_manualvaluation_3_fx_miss_raises_pricing_error(db: AsyncSession, test_user) -> None:
    """AC-pricing.manualvaluation.3: a missing FX rate surfaces as the pricing
    error family — the reporting caller owns the mapping to ReportError."""
    await record_manual_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType.TAX_REFUND,
        liquidity_class=ManualValuationLiquidityClass.LIQUID,
        as_of=date(2026, 5, 1),
        value=Decimal("1200.00"),
        currency="USD",
        source="IRAS",
    )
    await db.commit()

    with pytest.raises(PricingError):
        await build_manual_valuation_lines(
            db,
            test_user.id,
            as_of_date=date(2026, 5, 31),
            target_currency="SGD",
        )


async def test_AC_pricing_manualvaluation_4_component_recorded_after_as_of_is_warned(
    db: AsyncSession, test_user
) -> None:
    """AC-pricing.manualvaluation.4: a (component_type, source) combination whose
    only snapshot postdates as_of_date is absent from the lines and totals, and
    is disclosed through the warnings accumulator instead of vanishing silently
    (#1796); combinations with an eligible snapshot produce no warning."""
    await record_manual_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        as_of=date(2026, 5, 1),
        value=Decimal("1000000.00"),
        currency="SGD",
        source="appraisal",
    )
    # Recorded for the first time only after the report date below.
    await record_manual_valuation(
        db,
        test_user.id,
        component_type=ManualValuationComponentType.CPF_BALANCE,
        liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
        as_of=date(2026, 6, 15),
        value=Decimal("50000.00"),
        currency="SGD",
        source="cpf statement",
    )
    await db.commit()

    warnings: list[dict[str, str]] = []
    asset_lines, liability_lines = await build_manual_valuation_lines(
        db,
        test_user.id,
        as_of_date=date(2026, 5, 31),
        target_currency="SGD",
        warnings=warnings,
    )

    assert [line["name"] for line in asset_lines] == ["Valuation: appraisal (property value)"]
    assert liability_lines == []
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning["type"] == "valuation_component_not_yet_recorded"
    assert warning["component_type"] == "cpf_balance"
    assert warning["source"] == "cpf statement"
    assert warning["as_of_date"] == "2026-05-31"
    assert warning["earliest_as_of_date"] == "2026-06-15"
    assert "cpf statement" in warning["message"]

    # A view that excludes restricted/illiquid components must not disclose
    # their existence via gap warnings either (#1796 CR follow-up): the CPF
    # combo is RESTRICTED, so the exclusive view carries no warning for it.
    exclusive_warnings: list[dict[str, str]] = []
    await build_manual_valuation_lines(
        db,
        test_user.id,
        as_of_date=date(2026, 5, 31),
        target_currency="SGD",
        include_restricted=False,
        warnings=exclusive_warnings,
    )
    assert exclusive_warnings == []
