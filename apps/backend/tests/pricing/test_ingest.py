"""``ingest_statement_price`` — pricing's ``PriceObserved`` ingest subscriber (#1642).

The first cross-domain event *consumer* in this codebase (boundary ruling 4,
#1610): ``extraction`` publishes ``pricing.PriceObserved`` (``source=statement``)
through the platform outbox, and pricing ingests an id-referenced observation
copy — no shared transaction, no FK, the extraction fact id carried as
provenance. Delivery is at-least-once, so the handler MUST be idempotent
(dedup keyed by the event's natural key, the upstream fact id).

Anchors the ``AC-pricing.ingest.*`` roadmap group:

- AC-pricing.ingest.1 — a published extraction event results in exactly one
  pricing observation with correct fields + the provenance id.
- AC-pricing.ingest.2 — redelivering the same event does not duplicate.
- AC-pricing.ingest.3 — ``resolve()`` sees the ingested observation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.database import create_session_maker_from_db
from src.platform import DomainEvent, OutboxEventBus, OutboxRelay, SubscriberRegistry
from src.pricing import (
    Authority,
    ObservationSource,
    PriceableSubject,
    PriceObserved,
    ResolutionPolicy,
    SqlObservationRepository,
    ingest_statement_price,
    resolve,
    subscribe_price_ingest,
)
from src.pricing.base.events import EVENT_TYPE
from src.pricing.orm.statement_observation import StatementPriceObservation

pytestmark = pytest.mark.asyncio


def _statement_event(
    *,
    fact_id,
    user_id,
    symbol: str = "AAPL",
    as_of: date = date(2026, 6, 1),
    value: Decimal = Decimal("185.50"),
    currency: str = "USD",
    occurred_at: datetime | None = None,
) -> PriceObserved:
    """The event extraction's publisher will emit: a statement-extracted unit price."""
    return PriceObserved.create(
        observation_id=fact_id,
        subject=PriceableSubject.security(symbol),
        as_of=as_of,
        source=ObservationSource.STATEMENT,
        value=value,
        currency=currency,
        user_id=user_id,
        occurred_at=occurred_at or datetime.now(UTC),
    )


async def _ingested_rows(db) -> list[StatementPriceObservation]:
    result = await db.execute(select(StatementPriceObservation).order_by(StatementPriceObservation.created_at))
    return list(result.scalars().all())


async def test_AC_pricing_ingest_1_extraction_event_lands_as_one_provenanced_observation(db, test_user):
    """AC-pricing.ingest.1: publish from the extraction side -> relay -> exactly one copy.

    End to end through the real seams: the event is enqueued through the outbox
    (``source_pkg="extraction"``, as extraction's publisher will), committed, and
    dispatched by ``OutboxRelay`` to the handler ``subscribe_price_ingest`` wired —
    the same registration the app composition root performs at startup.
    """
    fact_id = uuid4()
    occurred_at = datetime.now(UTC)
    bus = OutboxEventBus(db, source_pkg="extraction")
    bus.publish(_statement_event(fact_id=fact_id, user_id=test_user.id, occurred_at=occurred_at))
    await db.commit()

    registry = SubscriberRegistry()
    subscribe_price_ingest(registry, session_factory=create_session_maker_from_db(db))
    published = await OutboxRelay(registry).run_once(db)
    assert published == 1

    rows = await _ingested_rows(db)
    assert len(rows) == 1
    row = rows[0]
    assert row.source_observation_id == fact_id  # provenance: the extraction fact id
    assert row.user_id == test_user.id
    assert row.subject_kind == "security"
    assert row.subject_key == "AAPL"
    assert row.value == Decimal("185.50")
    assert row.currency == "USD"
    assert row.as_of == date(2026, 6, 1)
    assert row.observed_at == occurred_at


async def test_AC_pricing_ingest_2_redelivery_through_the_relay_does_not_duplicate(db, test_user):
    """AC-pricing.ingest.2: at-least-once delivery of the same fact collapses to one row."""
    fact_id = uuid4()
    event = _statement_event(fact_id=fact_id, user_id=test_user.id)
    bus = OutboxEventBus(db, source_pkg="extraction")
    bus.publish(event)
    bus.publish(event)  # the same fact delivered twice (at-least-once)
    await db.commit()

    registry = SubscriberRegistry()
    subscribe_price_ingest(registry, session_factory=create_session_maker_from_db(db))
    published = await OutboxRelay(registry).run_once(db)
    assert published == 2  # both outbox rows were dispatched...

    rows = await _ingested_rows(db)
    assert len(rows) == 1  # ...but the duplicate was a no-op
    assert rows[0].source_observation_id == fact_id


async def test_AC_pricing_ingest_2_direct_redelivery_is_a_no_op(db, test_user):
    """AC-pricing.ingest.2: calling the handler twice with the same event ingests once.

    Models the crash-before-mark redelivery (the relay died after the handler ran
    but before ``mark_published`` committed): the second delivery must not raise
    and must not write a second row.
    """
    event = _statement_event(fact_id=uuid4(), user_id=test_user.id)

    first = await ingest_statement_price(db, event)
    again = await ingest_statement_price(db, event)

    assert first is not None
    assert first.source is ObservationSource.STATEMENT
    assert again is None  # duplicate -> no-op
    assert len(await _ingested_rows(db)) == 1


async def test_AC_pricing_ingest_3_ingested_observation_is_resolvable(db, test_user):
    """AC-pricing.ingest.3: the ingested copy is a first-class resolve() candidate."""
    event = _statement_event(fact_id=uuid4(), user_id=test_user.id)
    await ingest_statement_price(db, event)
    await db.commit()

    subject = PriceableSubject.security("AAPL")
    repo = SqlObservationRepository(db)
    candidates = await repo.candidates(subject, date(2026, 6, 30), user_id=test_user.id)
    resolved = resolve(subject, date(2026, 6, 30), ResolutionPolicy(), candidates)

    assert resolved.source is ObservationSource.STATEMENT
    assert resolved.authority is Authority.STATEMENT
    assert resolved.value == Decimal("185.50")
    assert resolved.currency == "USD"


async def test_statement_candidates_are_user_scoped(db, test_user):
    """Another user's (or an anonymous) read never sees this user's statement prices."""
    await ingest_statement_price(db, _statement_event(fact_id=uuid4(), user_id=test_user.id))
    await db.commit()

    subject = PriceableSubject.security("AAPL")
    repo = SqlObservationRepository(db)
    assert await repo.candidates(subject, date(2026, 6, 30), user_id=uuid4()) == []
    assert await repo.candidates(subject, date(2026, 6, 30), user_id=None) == []


async def test_pricing_own_manual_event_is_not_ingested(db, test_user):
    """The handler only ingests ``source=statement``: pricing's own publications
    (manual/override) already live in pricing's store — copying them would
    double-count the observation."""
    event = PriceObserved.create(
        observation_id=uuid4(),
        subject=PriceableSubject.component("property_value"),
        as_of=date(2026, 6, 1),
        source=ObservationSource.MANUAL,
        value=Decimal("500000"),
        currency="SGD",
        user_id=test_user.id,
        occurred_at=datetime.now(UTC),
    )

    assert await ingest_statement_price(db, event) is None
    assert await _ingested_rows(db) == []


async def test_malformed_statement_event_is_skipped_not_fatal(db, test_user):
    """A malformed/unresolvable payload is logged and skipped, never raised.

    Failure is deterministic (retrying the same bad payload can never succeed),
    and a raise would wedge the relay batch and block every later event behind
    the poison row — so the handler degrades to a loud no-op.
    """
    bad = DomainEvent(event_type=EVENT_TYPE, occurred_at=datetime.now(UTC))
    object.__setattr__(
        bad,
        "payload",
        lambda: {"source": "statement", "observation_id": "not-a-uuid"},
    )
    assert await ingest_statement_price(db, bad) is None

    negative = _statement_event(fact_id=uuid4(), user_id=test_user.id)
    object.__setattr__(
        negative,
        "payload",
        lambda: {**PriceObserved.payload(negative), "value": "-1"},
    )
    assert await ingest_statement_price(db, negative) is None

    missing_user = _statement_event(fact_id=uuid4(), user_id=None)
    assert await ingest_statement_price(db, missing_user) is None

    assert await _ingested_rows(db) == []
