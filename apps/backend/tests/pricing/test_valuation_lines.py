from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.pricing import ManualValuationComponentType, ManualValuationLiquidityClass, PricingError, ValuationService, build_manual_valuation_lines, build_manual_valuation_lines_series, record_manual_valuation
from src.pricing.orm.market_data import FxRate

pytestmark = pytest.mark.asyncio


async def test_AC_pricing_manualvaluation_3_4_lines_split_fx_miss_and_future_warning(db: AsyncSession, test_user) -> None:
    await record_manual_valuation(db, test_user.id, component_type=ManualValuationComponentType.PROPERTY_VALUE, liquidity_class=ManualValuationLiquidityClass.ILLIQUID, as_of=date(2026, 5, 1), value=Decimal("1000000.00"), currency="USD", source="appraisal")
    await record_manual_valuation(db, test_user.id, component_type=ManualValuationComponentType.MORTGAGE_BALANCE, liquidity_class=ManualValuationLiquidityClass.LIABILITY, as_of=date(2026, 5, 1), value=Decimal("400000.00"), currency="SGD", source="bank")
    await record_manual_valuation(db, test_user.id, component_type=ManualValuationComponentType.CPF_BALANCE, liquidity_class=ManualValuationLiquidityClass.RESTRICTED, as_of=date(2026, 6, 15), value=Decimal("50000.00"), currency="SGD", source="cpf statement")
    await db.commit()
    with pytest.raises(PricingError):
        await build_manual_valuation_lines(db, test_user.id, as_of_date=date(2026, 5, 31), target_currency="SGD")

    db.add(FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.350000"), rate_date=date(2026, 5, 31), source="test"))
    await db.commit()
    warnings: list[dict[str, str]] = []
    excl_warnings: list[dict[str, str]] = []
    assets, liabs = await build_manual_valuation_lines(db, test_user.id, as_of_date=date(2026, 5, 31), target_currency="SGD", warnings=warnings)
    await build_manual_valuation_lines(db, test_user.id, as_of_date=date(2026, 5, 31), target_currency="SGD", include_restricted=False, warnings=excl_warnings)
    a, liab, w = assets[0], liabs[0], warnings[0]
    assert (
        (len(assets), len(liabs), a["type"], a["amount"], a["source_currency"], "confidence_tier" not in a, a["provenance"], a["allocation_asset_class"], a["allocation_source_type"], a["name"]),
        (liab["type"], liab["amount"], liab["allocation_asset_class"], liab["allocation_liquidity_class"]),
        (len(warnings), w["type"], w["component_type"], w["source"], w["as_of_date"], w["earliest_as_of_date"], "cpf statement" in w["message"], excl_warnings),
    ) == (
        (1, 1, "ASSET", Decimal("1350000.00"), "USD", True, "manual", "real_estate", "manual_valuation", "Valuation: appraisal (property value)"),
        ("LIABILITY", Decimal("400000.00"), "real_estate", ManualValuationLiquidityClass.LIABILITY.value),
        (1, "valuation_component_not_yet_recorded", "cpf_balance", "cpf statement", "2026-05-31", "2026-06-15", True, []),
    )


async def test_AC_pricing_manualvaluation_11_series_equals_one_build_per_date(db: AsyncSession, test_user, monkeypatch) -> None:
    await record_manual_valuation(db, test_user.id, component_type=ManualValuationComponentType.RSU, liquidity_class=ManualValuationLiquidityClass.RESTRICTED, as_of=date(2026, 5, 10), value=Decimal("1234.57"), currency="USD", source="employer")
    await db.commit()
    with pytest.raises(PricingError, match="No FX rate available"):
        await build_manual_valuation_lines_series(db, test_user.id, as_of_dates=[date(2026, 5, 9), date(2026, 5, 10)], target_currency="SGD")

    for as_of, val in ((date(2026, 5, 3), "900000.00"), (date(2026, 5, 20), "950000.00")):
        await record_manual_valuation(db, test_user.id, component_type=ManualValuationComponentType.PROPERTY_VALUE, liquidity_class=ManualValuationLiquidityClass.ILLIQUID, as_of=as_of, value=Decimal(val), currency="SGD", source="appraisal")
    for val in ("400000.00", "410000.00"):
        await record_manual_valuation(db, test_user.id, component_type=ManualValuationComponentType.MORTGAGE_BALANCE, liquidity_class=ManualValuationLiquidityClass.LIABILITY, as_of=date(2026, 5, 3), value=Decimal(val), currency="SGD", source="bank")
    db.add_all([FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.341100"), rate_date=date(2026, 5, 1), source="test"), FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.352200"), rate_date=date(2026, 5, 15), source="test")])
    await db.commit()

    dates, reads, orig = [date(2026, 5, day) for day in range(1, 32)], [], ValuationService.get_latest_valuation_components

    async def counting(self, db, user_id, *, as_of_date, include_restricted=True):
        reads.append(as_of_date)
        return await orig(self, db, user_id, as_of_date=as_of_date, include_restricted=include_restricted)

    monkeypatch.setattr(ValuationService, "get_latest_valuation_components", counting)
    for inc in (True, False):
        reads.clear()
        series = await build_manual_valuation_lines_series(
            db, test_user.id, as_of_dates=dates, target_currency="sgd", include_restricted=inc
        )
        series_reads = list(reads)
        assert (
            series_reads,
            all(
                [
                    series[d]
                    == await build_manual_valuation_lines(
                        db, test_user.id, as_of_date=d, target_currency="sgd", include_restricted=inc
                    )
                    for d in dates
                ]
            ),
        ) == ([date(2026, 5, 3), date(2026, 5, 10), date(2026, 5, 20)], True)
    full_scope = await build_manual_valuation_lines_series(db, test_user.id, as_of_dates=[date(2026, 5, 16)], target_currency="sgd", include_restricted=True)
    assert (series[date(2026, 5, 2)], series[date(2026, 5, 16)][1], [line["amount"] for line in full_scope[date(2026, 5, 16)][1]]) == (([], []), [], [Decimal("410000.00")])
