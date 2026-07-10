"""``get_exchange_rate``/``get_average_rate`` — the FX-specific lookup wrappers.

Pre-AC-roadmap structural tests (the pricing package's roadmap is still
empty, #1610 P5) — see ``docs/project/traceability-exceptions.md``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.pricing.base.errors import NoObservationError, PricingError
from src.pricing.extension.fx import get_average_rate, get_exchange_rate
from src.pricing.orm.market_data import FxRate

pytestmark = pytest.mark.asyncio


async def test_identity_rate_never_touches_the_database(db: AsyncSession):
    # No FxRate row exists at all — if this reached the DB path, it would
    # raise NoObservationError instead of returning the identity rate.
    rate = await get_exchange_rate(db, "sgd", "SGD", date(2026, 6, 1))
    assert rate == Decimal("1")


async def test_resolves_the_most_recent_rate_on_or_before_the_date(db: AsyncSession):
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.30"),
                rate_date=date(2026, 1, 1),
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.35"),
                rate_date=date(2026, 6, 1),
                source="test",
            ),
        ]
    )
    await db.commit()

    rate = await get_exchange_rate(db, "USD", "SGD", date(2026, 6, 15))
    assert rate == Decimal("1.35")


async def test_raises_no_observation_error_when_no_rate_exists(db: AsyncSession):
    with pytest.raises(NoObservationError):
        await get_exchange_rate(db, "USD", "SGD", date(2026, 6, 1))


async def test_average_rate_identity_never_touches_the_database(db: AsyncSession):
    rate = await get_average_rate(db, "SGD", "sgd", date(2026, 1, 1), date(2026, 6, 1))
    assert rate == Decimal("1")


async def test_average_rate_rejects_an_inverted_range(db: AsyncSession):
    with pytest.raises(PricingError):
        await get_average_rate(db, "USD", "SGD", date(2026, 6, 1), date(2026, 1, 1))


async def test_average_rate_averages_observations_within_the_range(db: AsyncSession):
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.30"),
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
            # Outside the range — must not pull the average down.
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("0.10"),
                rate_date=date(2026, 1, 1),
                source="test",
            ),
        ]
    )
    await db.commit()

    rate = await get_average_rate(db, "USD", "SGD", date(2026, 6, 1), date(2026, 6, 30))
    assert rate == Decimal("1.35")


async def test_average_rate_falls_back_to_period_end_spot_rate_when_range_is_empty(
    db: AsyncSession,
):
    # Predates the queried range entirely — no row falls inside
    # [Jun 1, Jun 30], so the average path finds nothing and falls back to
    # get_exchange_rate(end_date), which resolves this as "the most recent
    # observation on or before Jun 30".
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

    rate = await get_average_rate(db, "USD", "SGD", date(2026, 6, 1), date(2026, 6, 30))
    assert rate == Decimal("1.35")
