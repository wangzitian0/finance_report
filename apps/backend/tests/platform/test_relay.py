"""The relay drains committed pending rows post-commit (AC-platform.1.2 / AC-platform.1.3).

Proves the read half of the outbox: ``run_once`` dispatches each pending row to
its subscribed handlers with the rehydrated event, marks the row published, and a
second ``run_once`` does NOT re-dispatch it. Re-delivery of a still-pending row is
safe for an idempotent handler (at-least-once is the contract).
"""

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from common.testing.ac_proof import ac_proof

from src.platform import (
    DomainEvent,
    Outbox,
    OutboxEventBus,
    OutboxRelay,
    SubscriberRegistry,
)
from src.platform.extension import STATUS_PUBLISHED


def _event(name="counter.Incremented", count=1):
    ev = DomainEvent(event_type=name, occurred_at=datetime.now(UTC))
    object.__setattr__(ev, "payload", lambda: {"count": count, "aggregate_id": "u1"})
    return ev


async def _seed(db, *, n=1, name="counter.Incremented"):
    bus = OutboxEventBus(db, source_pkg="counter")
    for i in range(n):
        bus.publish(_event(name=name, count=i + 1))
    await db.commit()


@ac_proof(proof_id="test_relay_dispatches_pending", ac_ids=["AC-platform.1.2"], ci_tier="pr_ci")
@pytest.mark.asyncio
async def test_run_once_dispatches_and_marks_published(db):
    """AC-platform.1.2: run_once invokes the handler with the event, then marks published."""
    registry = SubscriberRegistry()
    seen: list[dict] = []
    registry.subscribe("counter.Incremented", lambda e: seen.append(e.payload()))

    await _seed(db, n=2)
    relay = OutboxRelay(registry)

    published = await relay.run_once(db)

    assert published == 2
    assert [p["count"] for p in seen] == [1, 2]  # delivered in enqueue (id) order
    rows = (await db.execute(sa.select(Outbox).order_by(Outbox.id))).scalars().all()
    assert all(r.status == STATUS_PUBLISHED and r.published_at is not None for r in rows)


@pytest.mark.asyncio
async def test_run_once_awaits_async_handlers(db):
    """An async subscriber (e.g. a DB-writing ingest handler) is awaited, not dropped.

    Cross-domain consumers (#1642's pricing ingest is the precedent) need an
    ``AsyncSession`` inside the handler, so ``EventHandler`` admits coroutine
    functions and the relay awaits the returned awaitable before marking the
    row published.
    """
    registry = SubscriberRegistry()
    seen: list[int] = []

    async def handler(e: DomainEvent) -> None:
        seen.append(e.payload()["count"])

    registry.subscribe("counter.Incremented", handler)
    await _seed(db, n=1)

    assert await OutboxRelay(registry).run_once(db) == 1
    assert seen == [1]


@ac_proof(proof_id="test_relay_no_redispatch", ac_ids=["AC-platform.1.3"], ci_tier="pr_ci")
@pytest.mark.asyncio
async def test_second_run_does_not_redispatch_published(db):
    """AC-platform.1.3: a second run_once does NOT re-deliver already-published rows."""
    registry = SubscriberRegistry()
    deliveries: list[str] = []
    registry.subscribe("counter.Incremented", lambda e: deliveries.append(e.event_type))

    await _seed(db, n=1)
    relay = OutboxRelay(registry)

    assert await relay.run_once(db) == 1
    assert await relay.run_once(db) == 0  # nothing pending the second time
    assert deliveries == ["counter.Incremented"]  # delivered exactly once


@ac_proof(proof_id="test_relay_redelivery_idempotent", ac_ids=["AC-platform.1.3"], ci_tier="pr_ci")
@pytest.mark.asyncio
async def test_redelivery_of_pending_is_idempotent_safe(db):
    """AC-platform.1.3: re-delivering a still-pending row twice is safe for an idempotent handler.

    Models at-least-once: if a pass crashes before marking published, the next
    pass redelivers. An idempotent handler keyed by aggregate_id collapses the
    duplicate to a single effect.
    """
    registry = SubscriberRegistry()
    applied: set[str] = set()
    events: list[str] = []

    def idempotent_handler(e: DomainEvent) -> None:
        events.append(e.event_type)
        applied.add(e.payload()["aggregate_id"])  # set => duplicate is a no-op

    registry.subscribe("counter.Incremented", idempotent_handler)
    await _seed(db, n=1)

    # Dispatch the same pending rows twice WITHOUT marking published in between
    # (simulating a crash-before-mark redelivery), by reading pending directly.
    from src.platform.extension import SqlOutboxRepository

    repo = SqlOutboxRepository(db)
    for _ in range(2):
        for row in await repo.fetch_pending(limit=10):
            for handler in registry.handlers_for(row.event_type):
                handler(_event_from_row(row))

    assert len(events) == 2  # handler invoked twice (at-least-once)
    assert applied == {"u1"}  # but the idempotent effect collapses to one


def _event_from_row(row: Outbox) -> DomainEvent:
    ev = DomainEvent(event_type=row.event_type, occurred_at=row.occurred_at)
    object.__setattr__(ev, "payload", lambda: dict(row.payload))
    return ev
