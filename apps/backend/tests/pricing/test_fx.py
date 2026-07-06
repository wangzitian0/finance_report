"""``get_exchange_rate`` — the FX-specific lookup wrapper.

Pre-AC-roadmap structural tests (the pricing package's roadmap is still
empty, #1610 P5) — see ``docs/project/traceability-exceptions.md``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.market_data import FxRate
from src.pricing.base.errors import NoObservationError
from src.pricing.extension.fx import get_exchange_rate

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
