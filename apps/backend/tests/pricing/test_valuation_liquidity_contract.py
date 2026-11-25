from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import src.pricing.extension.fx as fx_module
from src.pricing import ManualValuationComponentType, ManualValuationLiquidityClass, build_manual_valuation_lines
from src.pricing.base.errors import NoObservationError, PricingError
from src.pricing.extension.valuation import ValuationComponentItem, split_net_worth_scope
from src.pricing.orm.manual_valuation import ManualValuationSnapshot


async def test_valuation_lines_liquidity_classification_contract(db: AsyncSession, test_user):
    as_of = date(2025, 4, 30)
    db.add_all(
        [
            ManualValuationSnapshot(
                user_id=test_user.id,
                as_of_date=as_of,
                source="Fixed Deposit",
                component_type=ManualValuationComponentType.LONG_TERM_SAVINGS,
                liquidity_class=ManualValuationLiquidityClass.LIQUID,
                currency="SGD",
                value=Decimal("50000.00"),
            ),
            ManualValuationSnapshot(
                user_id=test_user.id,
                as_of_date=as_of,
                source="Primary Residence",
                component_type=ManualValuationComponentType.PROPERTY_VALUE,
                liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
                currency="SGD",
                value=Decimal("500000.00"),
            ),
        ]
    )
    await db.commit()
    assets, _ = await build_manual_valuation_lines(
        db, test_user.id, as_of_date=as_of, target_currency="SGD", include_restricted=True
    )
    liquid, _ = await build_manual_valuation_lines(
        db, test_user.id, as_of_date=as_of, target_currency="SGD", include_restricted=False
    )
    assert (
        {line["name"]: line["allocation_liquidity_class"] for line in assets},
        [line["name"] for line in liquid],
    ) == (
        {
            "Valuation: Fixed Deposit (long term savings)": ManualValuationLiquidityClass.LIQUID.value,
            "Valuation: Primary Residence (property value)": ManualValuationLiquidityClass.ILLIQUID.value,
        },
        ["Valuation: Fixed Deposit (long term savings)"],
    )


def _comp(ctype, lclass, source) -> ValuationComponentItem:
    return ValuationComponentItem(
        id=uuid4(),
        component_type=ctype.value,
        liquidity_class=lclass.value,
        as_of_date=date(2026, 9, 30),
        value=Decimal("1000.00"),
        currency="SGD",
        source=source,
    )


def test_AC_pricing_manualvaluation_12_scope_excludes_a_liability_with_its_asset() -> None:
    prop = _comp(ManualValuationComponentType.PROPERTY_VALUE, ManualValuationLiquidityClass.ILLIQUID, "Condo")
    mort = _comp(ManualValuationComponentType.MORTGAGE_BALANCE, ManualValuationLiquidityClass.LIABILITY, "Condo loan")
    esop = _comp(ManualValuationComponentType.ESOP, ManualValuationLiquidityClass.RESTRICTED, "ESOP")
    tax_p = _comp(ManualValuationComponentType.TAX_PAYABLE, ManualValuationLiquidityClass.LIABILITY, "Income tax")
    tax_r = _comp(ManualValuationComponentType.TAX_REFUND, ManualValuationLiquidityClass.LIQUID, "Refund")
    pa, ma = (
        _comp(ManualValuationComponentType.PROPERTY_VALUE, ManualValuationLiquidityClass.ILLIQUID, "Property A"),
        _comp(ManualValuationComponentType.MORTGAGE_BALANCE, ManualValuationLiquidityClass.LIABILITY, "Mortgage A"),
    )
    pb, mb = (
        _comp(ManualValuationComponentType.PROPERTY_VALUE, ManualValuationLiquidityClass.LIQUID, "Property B"),
        _comp(ManualValuationComponentType.MORTGAGE_BALANCE, ManualValuationLiquidityClass.LIABILITY, "Mortgage B"),
    )
    comps = [prop, mort, esop, tax_p, tax_r]
    assert (
        tuple([i.source for i in s] for s in split_net_worth_scope(comps, include_restricted=False)),
        tuple([i.source for i in s] for s in split_net_worth_scope([mort, tax_r], include_restricted=False)),
        tuple(
            [i.source for i in s]
            for s in split_net_worth_scope([mort, tax_r], include_restricted=False, unrecorded_assets=[prop])
        ),
        tuple([i.source for i in s] for s in split_net_worth_scope([pa, ma, pb, mb], include_restricted=False)),
        split_net_worth_scope(comps, include_restricted=True),
    ) == (
        (["Income tax", "Refund"], ["Condo", "Condo loan", "ESOP"]),
        (["Condo loan", "Refund"], []),
        (["Refund"], ["Condo loan"]),
        (["Property B", "Mortgage B"], ["Property A", "Mortgage A"]),
        (comps, []),
    )


async def test_AC_pricing_manualvaluation_13_excluded_line_errors_by_type(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.add(
        ManualValuationSnapshot(
            user_id=test_user.id,
            as_of_date=date(2026, 9, 30),
            source="Employer RSU",
            component_type=ManualValuationComponentType.RSU,
            liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
            currency="USD",
            value=Decimal("1000.00"),
        )
    )
    await db.commit()

    async def build(err: Exception) -> list[dict]:
        monkeypatch.setattr(fx_module, "convert_amount", lambda *_a, **_kw: (_ for _ in ()).throw(err))
        excluded: list[dict] = []
        await build_manual_valuation_lines(
            db,
            test_user.id,
            as_of_date=date(2026, 10, 23),
            target_currency="SGD",
            include_restricted=False,
            excluded_lines=excluded,
        )
        return excluded

    missing = await build(NoObservationError("No FX rate available for USD/SGD on 2026-10-23"))
    failed = await build(PricingError("invalid FX conversion boundary for USD/SGD"))
    assert (
        [(line["amount"], line["conversion_warning"]["type"]) for line in missing],
        [(line["amount"], line["conversion_warning"]["type"]) for line in failed],
    ) == ([(None, "missing_fx_rate_excluded_holding")], [(None, "fx_conversion_failed_excluded_holding")])
    with pytest.raises(RuntimeError, match="connection lost"):
        await build(RuntimeError("connection lost"))
