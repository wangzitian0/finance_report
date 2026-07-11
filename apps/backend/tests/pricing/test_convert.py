"""``convert_amount``/``convert_money``/``convert_to_base`` — the lookup+math bridges.

Pre-AC-roadmap structural tests (the pricing package's roadmap is still
empty, #1610 P5) — see ``docs/project/traceability-exceptions.md``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import Money
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
