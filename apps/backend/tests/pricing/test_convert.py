"""``convert_amount``/``convert_money``/``convert_to_base`` — the lookup+math bridges.

Pre-AC-roadmap structural tests (the pricing package's roadmap is still
empty, #1610 P5) — see ``docs/project/traceability-exceptions.md``.
The ``AC-pricing.fx.3`` tests and the relocated ``AC-audit.31.2`` proof
anchor the #1610 P2 absorption of the retired ``services/fx.py`` surface
(average-rate windows on the ``convert_*`` trio) into this package.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from common.testing.ac_proof import ac_proof
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import ExchangeRate, Money
from src.pricing import FxWarning, PricingError
from src.pricing.base.errors import NoObservationError
from src.pricing.extension.fx import convert_amount, convert_money, convert_to_base
from src.pricing.orm.market_data import FxRate

pytestmark = pytest.mark.asyncio


async def test_convert_amount_is_a_noop_for_same_currency(db: AsyncSession):
    result = await convert_amount(db, Decimal("100"), "SGD", "sgd", date(2026, 6, 1))
    assert result == Decimal("100")


async def test_convert_amount_uses_the_resolved_rate(db: AsyncSession):
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.35"),
            rate_date=date(2026, 6, 1),
            source="test",
        )
    )
    await db.commit()

    result = await convert_amount(db, Decimal("100"), "USD", "SGD", date(2026, 6, 15))
    assert result == Decimal("135.00")


async def test_convert_amount_raises_when_no_rate_exists(db: AsyncSession):
    with pytest.raises(NoObservationError):
        await convert_amount(db, Decimal("100"), "USD", "SGD", date(2026, 6, 1))


async def test_convert_money_returns_money_in_the_target_currency(db: AsyncSession):
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.35"),
            rate_date=date(2026, 6, 1),
            source="test",
        )
    )
    await db.commit()

    result = await convert_money(db, Money(Decimal("100"), "USD"), "SGD", date(2026, 6, 15))
    assert result == Money(Decimal("135.00"), "SGD")


async def test_convert_money_lazy_load_falls_back_to_the_crawler_path(db: AsyncSession):
    """#1641/#1643 fallback parity: ``convert_money(..., lazy_load=True)`` on a
    rate miss derives the inverse rate instead of raising — the behavior the
    portfolio read-side relied on in ``services/fx.py``."""
    db.add(
        FxRate(
            base_currency="SGD",
            quote_currency="HKD",
            rate=Decimal("5.800000"),
            rate_date=date(2026, 6, 30),
            source="test",
        )
    )
    await db.commit()

    result = await convert_money(db, Money(Decimal("100"), "HKD"), "SGD", date(2026, 6, 30), lazy_load=True)
    assert result == Money(Decimal("17.24"), "SGD")


async def test_convert_to_base_uses_the_configured_base_currency(db: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    import src.pricing.extension.fx as fx_module

    monkeypatch.setattr(fx_module.settings, "base_currency", "SGD")
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.35"),
            rate_date=date(2026, 6, 1),
            source="test",
        )
    )
    await db.commit()

    result = await convert_to_base(db, Decimal("100"), "USD", date(2026, 6, 15))
    assert result == Decimal("135.00")


async def test_AC_pricing_fx_3_convert_amount_uses_average_rate_window(db: AsyncSession):
    """AC-pricing.fx.3: ``average_start``/``average_end`` route the conversion
    through the period-average rate instead of the spot rate
    (``services/fx.py`` parity — the income-statement convention)."""
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.20"),
                rate_date=date(2026, 6, 1),
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.40"),
                rate_date=date(2026, 6, 15),
                source="test",
            ),
        ]
    )
    await db.commit()

    result = await convert_amount(
        db,
        Decimal("10.00"),
        "USD",
        "SGD",
        date(2026, 6, 15),
        average_start=date(2026, 6, 1),
        average_end=date(2026, 6, 30),
    )

    assert result == Decimal("13.00")


async def test_AC_pricing_fx_3_convert_money_average_window_falls_back_with_warning(db: AsyncSession):
    """AC-pricing.fx.3: an empty average window falls back to the period-end
    spot rate and surfaces the fallback through ``fx_warnings``."""
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.35"),
            rate_date=date(2026, 1, 1),
            source="test",
        )
    )
    await db.commit()

    warnings: list[FxWarning] = []
    result = await convert_money(
        db,
        Money(Decimal("100"), "USD"),
        "SGD",
        date(2026, 6, 30),
        average_start=date(2026, 6, 1),
        average_end=date(2026, 6, 30),
        fx_warnings=warnings,
    )

    assert result == Money(Decimal("135.00"), "SGD")
    assert [w["type"] for w in warnings] == ["average_rate_fallback"]


async def test_AC_pricing_fx_3_convert_amount_average_window_miss_raises(db: AsyncSession):
    """AC-pricing.fx.3: when neither an average nor a period-end spot rate
    exists, the conversion still fails loudly with the pricing error family."""
    with pytest.raises(PricingError):
        await convert_amount(
            db,
            Decimal("10.00"),
            "USD",
            "SGD",
            date(2026, 6, 30),
            average_start=date(2026, 6, 1),
            average_end=date(2026, 6, 30),
        )


@ac_proof(
    proof_id="test_fx_convert_amount_uses_typed_money_exchange_rate",
    ac_ids=["AC-audit.31.2"],
    ci_tier="pr_ci",
)
async def test_AC12_31_2_convert_amount_routes_through_money_exchange_rate(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """AC-audit.31.2: service boundary wraps storage Decimal in Money + ExchangeRate.

    Relocated from ``tests/market_data/test_fx.py`` when #1610 P2 retired
    ``services/fx.py`` — pricing's ``convert_amount`` is now the single FX
    lookup+convert implementation the proof anchors to.
    """
    import src.pricing.extension.fx as fx_module

    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.200000"),
            rate_date=date(2026, 1, 1),
            source="test",
        )
    )
    await db.commit()

    calls: list[tuple[Money, ExchangeRate]] = []

    def fake_convert(money: Money, rate: ExchangeRate) -> Money:
        calls.append((money, rate))
        return Money(Decimal("120.00"), "SGD")

    monkeypatch.setattr(fx_module, "_money_convert", fake_convert)

    result = await convert_amount(db, Decimal("100.00"), "USD", "SGD", date(2026, 1, 1))

    assert result == Decimal("120.00")
    assert len(calls) == 1
    money, typed_rate = calls[0]
    assert money == Money(Decimal("100.00"), "USD")
    assert typed_rate == ExchangeRate("USD", "SGD", Decimal("1.200000"))


async def test_convert_amount_wraps_invalid_currency_as_pricing_error(db: AsyncSession, monkeypatch):
    """Legacy/provider rate rows with non-ISO codes should not leak Money errors."""
    import src.pricing.extension.fx as fx_module

    async def fake_get_exchange_rate(*args, **kwargs) -> Decimal:
        return Decimal("60000.000000")

    monkeypatch.setattr(fx_module, "get_exchange_rate", fake_get_exchange_rate)

    with pytest.raises(PricingError, match="invalid FX conversion boundary"):
        await convert_amount(db, Decimal("0.50"), "BTC", "USD", date(2026, 1, 1))
