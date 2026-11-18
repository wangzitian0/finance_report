from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.database import create_session_maker_from_db
from src.platform import DomainEvent, OutboxEventBus, OutboxRelay, SubscriberRegistry
from src.pricing import Authority, ObservationSource, PriceableSubject, PriceObserved, ResolutionPolicy, SqlObservationRepository, ingest_statement_price, resolve, subscribe_price_ingest
from src.pricing.base.events import EVENT_TYPE
from src.pricing.orm.statement_observation import StatementPriceObservation

pytestmark = pytest.mark.asyncio

_event = lambda *, fact_id, user_id, symbol="AAPL", as_of=date(2026, 6, 1), value=Decimal("185.50"), currency="USD", occurred_at=None: PriceObserved.create(observation_id=fact_id, subject=PriceableSubject.security(symbol), as_of=as_of, source=ObservationSource.STATEMENT, value=value, currency=currency, user_id=user_id, occurred_at=occurred_at or datetime.now(UTC))


async def _rows(db) -> list[StatementPriceObservation]:
    return list((await db.execute(select(StatementPriceObservation).order_by(StatementPriceObservation.created_at))).scalars().all())


@pytest.mark.parametrize("redeliver", [False, True])
async def test_AC_pricing_ingest_1_2_relay_lands_once_and_dedups(db, test_user, redeliver):
    fact_id, occurred_at = uuid4(), datetime.now(UTC)
    bus = OutboxEventBus(db, source_pkg="extraction")
    ev = _event(fact_id=fact_id, user_id=test_user.id, occurred_at=occurred_at)
    bus.publish(ev)
    if redeliver:
        bus.publish(ev)
    await db.commit()
    registry = SubscriberRegistry()
    subscribe_price_ingest(registry, session_factory=create_session_maker_from_db(db))
    published = await OutboxRelay(registry).run_once(db)
    rows = await _rows(db)
    r = rows[0]
    assert (published, len(rows), r.source_observation_id, r.user_id, r.subject_kind, r.subject_key, r.value, r.currency, r.as_of, r.observed_at) == (2 if redeliver else 1, 1, fact_id, test_user.id, "security", "AAPL", Decimal("185.50"), "USD", date(2026, 6, 1), occurred_at)


async def test_AC_pricing_ingest_2_3_direct_ingest_idempotent_resolvable_and_scoped(db, test_user):
    ev = _event(fact_id=uuid4(), user_id=test_user.id)
    first = await ingest_statement_price(db, ev)
    again = await ingest_statement_price(db, ev)
    await db.commit()
    subj = PriceableSubject.security("AAPL")
    repo = SqlObservationRepository(db)
    cands = await repo.candidates(subj, date(2026, 6, 30), user_id=test_user.id)
    resolved = resolve(subj, date(2026, 6, 30), ResolutionPolicy(), cands)
    assert (
        first.source,
        again,
        len(await _rows(db)),
        (resolved.source, resolved.authority, resolved.value, resolved.currency),
        await repo.candidates(subj, date(2026, 6, 30), user_id=uuid4()),
        await repo.candidates(subj, date(2026, 6, 30), user_id=None),
    ) == (ObservationSource.STATEMENT, None, 1, (ObservationSource.STATEMENT, Authority.STATEMENT, Decimal("185.50"), "USD"), [], [])


async def test_manual_and_malformed_statement_events_are_skipped(db, test_user):
    manual = PriceObserved.create(observation_id=uuid4(), subject=PriceableSubject.component("property_value"), as_of=date(2026, 6, 1), source=ObservationSource.MANUAL, value=Decimal("500000"), currency="SGD", user_id=test_user.id, occurred_at=datetime.now(UTC))
    bad = DomainEvent(event_type=EVENT_TYPE, occurred_at=datetime.now(UTC))
    object.__setattr__(bad, "payload", lambda: {"source": "statement", "observation_id": "not-a-uuid"})
    neg = _event(fact_id=uuid4(), user_id=test_user.id)
    object.__setattr__(neg, "payload", lambda: {**PriceObserved.payload(neg), "value": "-1"})
    no_user = _event(fact_id=uuid4(), user_id=None)
    assert ([await ingest_statement_price(db, e) for e in (manual, bad, neg, no_user)], await _rows(db)) == ([None, None, None, None], [])
