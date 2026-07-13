"""``record_manual_valuation``/``record_override`` — the write-side recorders.

Pre-AC-roadmap structural tests (the pricing package's roadmap is still
empty, #1610 P5) — see ``docs/project/traceability-exceptions.md``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer3 import ManualValuationSnapshot
from src.platform import Outbox
from src.pricing.base.events import EVENT_TYPE
from src.pricing.base.observation import Authority, ObservationSource
from src.pricing.extension.manual import record_manual_valuation, record_override
from src.pricing.extension.repository import SqlObservationRepository

pytestmark = pytest.mark.asyncio


async def _outbox_rows(db: AsyncSession):
    return (await db.execute(sa.select(Outbox).order_by(Outbox.id))).scalars().all()


async def test_record_manual_valuation_returns_a_manual_observation(db: AsyncSession, test_user):
    observation = await record_manual_valuation(
        db,
        test_user.id,
        component_type="property_value",
        liquidity_class="illiquid",
        as_of=date(2026, 6, 1),
        value=Decimal("500000"),
        currency="sgd",
        source="user-entry",
    )

    assert observation.source is ObservationSource.MANUAL
    assert observation.authority is Authority.MANUAL
    assert observation.value == Decimal("500000.00")
    assert observation.currency == "SGD"  # normalize_currency_code upper-cases


async def test_record_manual_valuation_correction_supersedes_without_duplicate_heads(db: AsyncSession, test_user):
    first = await record_manual_valuation(
        db,
        test_user.id,
        component_type="cpf_balance",
        liquidity_class="restricted",
        as_of=date(2026, 6, 1),
        value=Decimal("100000"),
        currency="SGD",
        source="user-entry",
    )
    second = await record_manual_valuation(
        db,
        test_user.id,
        component_type="cpf_balance",
        liquidity_class="restricted",
        as_of=date(2026, 6, 1),
        value=Decimal("101000"),
        currency="SGD",
        source="user-entry",
    )
    assert second.value == Decimal("101000.00")

    # Exactly one current head at the DB level (the partial-unique index
    # would have rejected a second commit if the ordered hand-off broke).
    heads = (
        (
            await db.execute(
                select(ManualValuationSnapshot)
                .where(ManualValuationSnapshot.user_id == test_user.id)
                .where(ManualValuationSnapshot.component_type == "cpf_balance")
                .where(ManualValuationSnapshot.superseded_by_id.is_(None))
            )
        )
        .scalars()
        .all()
    )
    assert len(heads) == 1
    assert heads[0].value == Decimal("101000.00")

    # Both versions are visible to the repository (bitemporal history).
    repo = SqlObservationRepository(db)
    candidates = await repo.candidates(second.subject, date(2026, 6, 15), user_id=test_user.id)
    assert {c.value for c in candidates} == {Decimal("100000.00"), Decimal("101000.00")}
    assert first.value == Decimal("100000.00")  # the superseded version, unchanged


async def test_record_override_is_resolvable_immediately(db: AsyncSession, test_user):
    observation = await record_override(
        db,
        test_user.id,
        asset_identifier="AAPL",
        as_of=date(2026, 6, 1),
        price=Decimal("185.50"),
        currency="usd",
    )
    assert observation.source is ObservationSource.OVERRIDE
    assert observation.authority is Authority.OVERRIDE
    assert observation.currency == "USD"

    repo = SqlObservationRepository(db)
    candidates = await repo.candidates(observation.subject, date(2026, 6, 15), user_id=test_user.id)
    assert len(candidates) == 1
    assert candidates[0].value == Decimal("185.50")


async def test_record_manual_valuation_enqueues_price_observed_atomically(db: AsyncSession, test_user):
    """The outbox row lands in the same transaction as the snapshot (record_increment pattern)."""
    observation = await record_manual_valuation(
        db,
        test_user.id,
        component_type="property_value",
        liquidity_class="illiquid",
        as_of=date(2026, 6, 1),
        value=Decimal("500000"),
        currency="SGD",
        source="user-entry",
    )
    await db.commit()

    rows = await _outbox_rows(db)
    assert len(rows) == 1
    row = rows[0]
    assert row.event_type == EVENT_TYPE  # "pricing.PriceObserved"
    assert row.source_pkg == "pricing"
    assert row.payload["observation_id"] == str(observation.id)
    assert row.payload["subject_kind"] == "component"
    assert row.payload["subject_key"] == "property_value"
    assert row.payload["source"] == "manual"


async def test_record_manual_valuation_rollback_leaves_neither_snapshot_nor_event(db: AsyncSession, test_user):
    user_id = test_user.id  # captured before rollback expires the fixture object
    await record_manual_valuation(
        db,
        user_id,
        component_type="property_value",
        liquidity_class="illiquid",
        as_of=date(2026, 6, 1),
        value=Decimal("500000"),
        currency="SGD",
        source="user-entry",
    )
    await db.flush()
    await db.rollback()

    heads = (
        (await db.execute(select(ManualValuationSnapshot).where(ManualValuationSnapshot.user_id == user_id)))
        .scalars()
        .all()
    )
    assert heads == []
    assert await _outbox_rows(db) == []


async def test_record_override_enqueues_price_observed(db: AsyncSession, test_user):
    observation = await record_override(
        db,
        test_user.id,
        asset_identifier="AAPL",
        as_of=date(2026, 6, 1),
        price=Decimal("185.50"),
        currency="USD",
    )
    await db.commit()

    rows = await _outbox_rows(db)
    assert len(rows) == 1
    row = rows[0]
    assert row.event_type == EVENT_TYPE
    assert row.source_pkg == "pricing"
    assert row.payload["observation_id"] == str(observation.id)
    assert row.payload["subject_kind"] == "security"
    assert row.payload["subject_key"] == "AAPL"
    assert row.payload["source"] == "override"
