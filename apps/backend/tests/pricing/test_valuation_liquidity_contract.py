"""AC-pricing.manualvaluation.3: Contract tests for manual valuation liquidity classification."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.pricing import (
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    build_manual_valuation_lines,
)
from src.pricing.extension.valuation import ValuationComponentItem, split_net_worth_scope
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


def _component(
    component_type: ManualValuationComponentType,
    liquidity_class: ManualValuationLiquidityClass,
    source: str,
) -> ValuationComponentItem:
    return ValuationComponentItem(
        id=uuid4(),
        component_type=component_type.value,
        liquidity_class=liquidity_class.value,
        as_of_date=date(2026, 9, 30),
        value=Decimal("1000.00"),
        currency="SGD",
        source=source,
    )


def test_AC_pricing_manualvaluation_12_scope_excludes_a_liability_with_its_asset() -> None:
    """AC-pricing.manualvaluation.12: a scope without restricted holdings excludes a liability with its asset (#2645, #2659).

    The excluded property takes its mortgage out. A mortgage linked to a liquid
    property stays even when another property is illiquid. A mortgage older than
    its unrecorded illiquid property is excluded too.
    """
    property_value = _component(
        ManualValuationComponentType.PROPERTY_VALUE, ManualValuationLiquidityClass.ILLIQUID, "Condo"
    )
    mortgage = _component(
        ManualValuationComponentType.MORTGAGE_BALANCE, ManualValuationLiquidityClass.LIABILITY, "Condo loan"
    )
    esop = _component(ManualValuationComponentType.ESOP, ManualValuationLiquidityClass.RESTRICTED, "ESOP")
    tax_payable = _component(
        ManualValuationComponentType.TAX_PAYABLE, ManualValuationLiquidityClass.LIABILITY, "Income tax"
    )
    tax_refund = _component(ManualValuationComponentType.TAX_REFUND, ManualValuationLiquidityClass.LIQUID, "Refund")
    components = [property_value, mortgage, esop, tax_payable, tax_refund]

    included, excluded = split_net_worth_scope(components, include_restricted=False)
    assert [item.source for item in included] == ["Income tax", "Refund"]
    assert [item.source for item in excluded] == ["Condo", "Condo loan", "ESOP"]

    included, excluded = split_net_worth_scope([mortgage, tax_refund], include_restricted=False)
    assert [item.source for item in included] == ["Condo loan", "Refund"]
    assert excluded == []

    # Unrecorded illiquid property on a later date still excludes its earlier mortgage (#2659 Case 3).
    included, excluded = split_net_worth_scope(
        [mortgage, tax_refund], include_restricted=False, unrecorded_assets=[property_value]
    )
    assert [item.source for item in included] == ["Refund"]
    assert [item.source for item in excluded] == ["Condo loan"]

    # Mixed liquidity in one class (#2659 Case 2): Mortgage B stays with liquid Property B.
    prop_a = _component(
        ManualValuationComponentType.PROPERTY_VALUE, ManualValuationLiquidityClass.ILLIQUID, "Property A"
    )
    mort_a = _component(
        ManualValuationComponentType.MORTGAGE_BALANCE, ManualValuationLiquidityClass.LIABILITY, "Mortgage A"
    )
    prop_b = _component(ManualValuationComponentType.PROPERTY_VALUE, ManualValuationLiquidityClass.LIQUID, "Property B")
    mort_b = _component(
        ManualValuationComponentType.MORTGAGE_BALANCE, ManualValuationLiquidityClass.LIABILITY, "Mortgage B"
    )
    included, excluded = split_net_worth_scope([prop_a, mort_a, prop_b, mort_b], include_restricted=False)
    assert [item.source for item in included] == ["Property B", "Mortgage B"]
    assert [item.source for item in excluded] == ["Property A", "Mortgage A"]

    included, excluded = split_net_worth_scope(components, include_restricted=True)
    assert included == components
    assert excluded == []


async def test_AC_pricing_manualvaluation_13_excluded_line_errors_by_type(
    db: AsyncSession, user_id, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-pricing.manualvaluation.13: an excluded line keeps a pricing FX error as a typed warning; other errors raise.

    A missing rate gives ``missing_fx_rate_excluded_holding``. Another pricing error
    gives ``fx_conversion_failed_excluded_holding``. An error outside the pricing
    family is not an FX gap, so it still raises (#2645).
    """
    import src.pricing.extension.fx as fx_module
    from src.pricing.base.errors import NoObservationError, PricingError

    db.add(
        ManualValuationSnapshot(
            user_id=user_id,
            as_of_date=date(2026, 9, 30),
            source="Employer RSU",
            component_type=ManualValuationComponentType.RSU,
            liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
            currency="USD",
            value=Decimal("1000.00"),
        )
    )
    await db.commit()

    async def build(error: Exception) -> list[dict]:
        async def fail(*_args, **_kwargs):
            raise error

        monkeypatch.setattr(fx_module, "convert_amount", fail)
        excluded: list[dict] = []
        await build_manual_valuation_lines(
            db,
            user_id,
            as_of_date=date(2026, 10, 23),
            target_currency="SGD",
            include_restricted=False,
            excluded_lines=excluded,
        )
        return excluded

    missing = await build(NoObservationError("No FX rate available for USD/SGD on 2026-10-23"))
    assert [(line["amount"], line["conversion_warning"]["type"]) for line in missing] == [
        (None, "missing_fx_rate_excluded_holding")
    ]
    failed = await build(PricingError("invalid FX conversion boundary for USD/SGD"))
    assert [(line["amount"], line["conversion_warning"]["type"]) for line in failed] == [
        (None, "fx_conversion_failed_excluded_holding")
    ]
    with pytest.raises(RuntimeError, match="connection lost"):
        await build(RuntimeError("connection lost"))
