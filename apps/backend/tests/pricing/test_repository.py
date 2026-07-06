"""``SqlObservationRepository`` — real DB-backed candidate retrieval + user scoping.

The critical property under test is the one the port's docstring promises:
``user_id=None`` never returns another user's manual/override data, and a
caller who passes the WRONG ``user_id`` gets a smaller result, never a leak
of someone else's row. These are pre-AC-roadmap structural tests (the
pricing package's roadmap is still empty, #1610 P5) — see
``docs/project/traceability-exceptions.md``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.layer3 import ManualValuationSnapshot
from src.models.market_data import FxRate, StockPrice
from src.models.portfolio import MarketDataOverride
from src.pricing.base.observation import Authority, ObservationSource
from src.pricing.base.subject import PriceableSubject
from src.pricing.extension.repository import SqlObservationRepository

pytestmark = pytest.mark.asyncio


async def test_fx_candidates_come_from_fx_rate_table(db: AsyncSession):
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

    repo = SqlObservationRepository(db)
    subject = PriceableSubject.currency_pair("USD", "SGD")
    candidates = await repo.candidates(subject, date(2026, 6, 1))

    assert len(candidates) == 1
    obs = candidates[0]
    assert obs.value == Decimal("1.35")
    assert obs.source is ObservationSource.CRAWLER
    assert obs.authority is Authority.CRAWLER


async def test_observation_id_matches_the_underlying_row_not_a_random_uuid(db: AsyncSession):
    """PriceObservation.id must be the real row id — an aggregate root's
    identity is meaningless if every read mints a fresh random one."""
    row = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.35"),
        rate_date=date(2026, 1, 1),
        source="test",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    repo = SqlObservationRepository(db)
    subject = PriceableSubject.currency_pair("USD", "SGD")
    candidates = await repo.candidates(subject, date(2026, 6, 1))

    assert candidates[0].id == row.id


async def test_fx_candidates_exclude_rows_after_as_of(db: AsyncSession):
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
                rate=Decimal("1.40"),
                rate_date=date(2026, 12, 1),
                source="test",
            ),
        ]
    )
    await db.commit()

    repo = SqlObservationRepository(db)
    subject = PriceableSubject.currency_pair("USD", "SGD")
    candidates = await repo.candidates(subject, date(2026, 6, 1))

    assert len(candidates) == 1
    assert candidates[0].value == Decimal("1.30")


async def test_security_candidates_combine_crawled_price_and_override(db: AsyncSession, test_user):
    db.add(
        StockPrice(
            symbol="AAPL",
            price=Decimal("180.00"),
            currency="USD",
            price_date=date(2026, 6, 1),
            source="test",
        )
    )
    db.add(
        MarketDataOverride(
            user_id=test_user.id,
            asset_identifier="AAPL",
            price_date=date(2026, 6, 1),
            price=Decimal("185.50"),
            currency="USD",
        )
    )
    await db.commit()

    repo = SqlObservationRepository(db)
    subject = PriceableSubject.security("AAPL")
    candidates = await repo.candidates(subject, date(2026, 6, 15), user_id=test_user.id)

    sources = {obs.source for obs in candidates}
    assert sources == {ObservationSource.CRAWLER, ObservationSource.OVERRIDE}
    override = next(o for o in candidates if o.source is ObservationSource.OVERRIDE)
    assert override.authority is Authority.OVERRIDE
    assert override.value == Decimal("185.50")


async def test_security_override_never_leaks_across_users(db: AsyncSession, test_user):
    from src.identity import User

    other_user = User(email="other-pricing-test@example.com", hashed_password="hashed")
    db.add(other_user)
    await db.commit()
    await db.refresh(other_user)

    db.add(
        MarketDataOverride(
            user_id=other_user.id,
            asset_identifier="TSLA",
            price_date=date(2026, 6, 1),
            price=Decimal("999.00"),
            currency="USD",
        )
    )
    await db.commit()

    repo = SqlObservationRepository(db)
    subject = PriceableSubject.security("TSLA")

    # Querying as test_user must NOT see other_user's override.
    as_test_user = await repo.candidates(subject, date(2026, 6, 15), user_id=test_user.id)
    assert as_test_user == []

    # Querying with no user_id must NOT see any user's override either.
    anonymous = await repo.candidates(subject, date(2026, 6, 15), user_id=None)
    assert anonymous == []

    # Querying as the actual owner does see it.
    as_owner = await repo.candidates(subject, date(2026, 6, 15), user_id=other_user.id)
    assert len(as_owner) == 1


async def test_component_candidates_require_a_user_id(db: AsyncSession, test_user):
    db.add(
        ManualValuationSnapshot(
            user_id=test_user.id,
            component_type="property_value",
            liquidity_class="illiquid",
            as_of_date=date(2026, 6, 1),
            value=Decimal("500000.00"),
            currency="SGD",
            source="test",
        )
    )
    await db.commit()

    repo = SqlObservationRepository(db)
    subject = PriceableSubject.component("property_value")

    assert await repo.candidates(subject, date(2026, 6, 15), user_id=None) == []

    owned = await repo.candidates(subject, date(2026, 6, 15), user_id=test_user.id)
    assert len(owned) == 1
    assert owned[0].source is ObservationSource.MANUAL
    assert owned[0].authority is Authority.MANUAL
    assert owned[0].value == Decimal("500000.00")


async def test_component_candidates_include_superseded_history_for_bitemporal_resolve(db: AsyncSession, test_user):
    """Both the original and its correction come back; resolve() (not the
    adapter) picks the winner by observed_at — proving the bitemporal split
    (#1610 ruling 3) falls out of resolve(), not a second filtering mechanism.

    Mirrors the ordered hand-off ``AssetService.create_valuation_snapshot``
    uses (services/assets.py): the new row is parked UNDER the prior head
    (``superseded_by_id=head.id``, valid — 0 heads momentarily), then the
    head is demoted (0 heads), then the new row is promoted to
    ``superseded_by_id=None`` (1 head) — three flushes, each individually
    valid under both the self-FK and the partial-unique index.
    """
    original = ManualValuationSnapshot(
        user_id=test_user.id,
        component_type="cpf_balance",
        liquidity_class="restricted",
        as_of_date=date(2026, 6, 1),
        value=Decimal("100000.00"),
        currency="SGD",
        source="user-entry",
    )
    db.add(original)
    await db.commit()
    await db.refresh(original)

    correction = ManualValuationSnapshot(
        id=uuid4(),
        user_id=test_user.id,
        component_type="cpf_balance",
        liquidity_class="restricted",
        as_of_date=date(2026, 6, 1),
        value=Decimal("101000.00"),
        currency="SGD",
        source="user-entry",
        version=2,
        superseded_by_id=original.id,
    )
    db.add(correction)
    await db.flush()
    original.superseded_by_id = correction.id
    await db.flush()
    correction.superseded_by_id = None
    await db.commit()

    repo = SqlObservationRepository(db)
    subject = PriceableSubject.component("cpf_balance")
    candidates = await repo.candidates(subject, date(2026, 6, 15), user_id=test_user.id)

    assert len(candidates) == 2
    assert {c.value for c in candidates} == {Decimal("100000.00"), Decimal("101000.00")}
