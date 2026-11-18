from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform.extension.sql import OutboxRecord
from src.pricing.base.events import EVENT_TYPE
from src.pricing.base.observation import Authority, ObservationSource
from src.pricing.extension.manual import record_manual_valuation, record_override
from src.pricing.extension.repository import SqlObservationRepository
from src.pricing.orm.manual_valuation import ManualValuationSnapshot

pytestmark = pytest.mark.asyncio


async def _outbox_rows(db: AsyncSession):
    return (await db.execute(sa.select(OutboxRecord).order_by(OutboxRecord.id))).scalars().all()


async def test_record_manual_valuation_supersedes_and_emits_outbox(db: AsyncSession, test_user):
    first = await record_manual_valuation(db, test_user.id, component_type="property_value", liquidity_class="illiquid", as_of=date(2026, 6, 1), value=Decimal("500000"), currency="sgd", source="user-entry")
    second = await record_manual_valuation(db, test_user.id, component_type="property_value", liquidity_class="illiquid", as_of=date(2026, 6, 1), value=Decimal("510000"), currency="SGD", source="user-entry")
    await db.commit()
    heads = (await db.execute(select(ManualValuationSnapshot).where(ManualValuationSnapshot.user_id == test_user.id, ManualValuationSnapshot.component_type == "property_value", ManualValuationSnapshot.superseded_by_id.is_(None)))).scalars().all()
    cands = await SqlObservationRepository(db).candidates(second.subject, date(2026, 6, 15), user_id=test_user.id)
    rows = await _outbox_rows(db)
    assert (
        (first.source, first.authority, first.value, first.currency),
        (second.value, len(heads), heads[0].value, {c.value for c in cands}),
        (len(rows), rows[1].event_type, rows[1].source_pkg, rows[1].payload["observation_id"], rows[1].payload["subject_kind"], rows[1].payload["subject_key"], rows[1].payload["source"]),
    ) == (
        (ObservationSource.MANUAL, Authority.MANUAL, Decimal("500000.00"), "SGD"),
        (Decimal("510000.00"), 1, Decimal("510000.00"), {Decimal("500000.00"), Decimal("510000.00")}),
        (2, EVENT_TYPE, "pricing", str(second.id), "component", "property_value", "manual"),
    )


async def test_record_manual_valuation_rollback_is_atomic(db: AsyncSession, test_user):
    user_id = test_user.id
    await record_manual_valuation(db, user_id, component_type="property_value", liquidity_class="illiquid", as_of=date(2026, 6, 1), value=Decimal("500000"), currency="SGD", source="user-entry")
    await db.flush()
    await db.rollback()
    assert ((await db.execute(select(ManualValuationSnapshot).where(ManualValuationSnapshot.user_id == user_id))).scalars().all(), await _outbox_rows(db)) == ([], [])


async def test_record_override_resolvable_and_enqueues_event(db: AsyncSession, test_user):
    obs = await record_override(db, test_user.id, asset_identifier="AAPL", as_of=date(2026, 6, 1), price=Decimal("185.50"), currency="usd")
    await db.commit()
    cands = await SqlObservationRepository(db).candidates(obs.subject, date(2026, 6, 15), user_id=test_user.id)
    rows = await _outbox_rows(db)
    assert (
        (obs.source, obs.authority, obs.currency, len(cands), cands[0].value),
        (len(rows), rows[0].event_type, rows[0].source_pkg, rows[0].payload["observation_id"], rows[0].payload["subject_kind"], rows[0].payload["subject_key"], rows[0].payload["source"]),
    ) == ((ObservationSource.OVERRIDE, Authority.OVERRIDE, "USD", 1, Decimal("185.50")), (1, EVENT_TYPE, "pricing", str(obs.id), "security", "AAPL", "override"))
