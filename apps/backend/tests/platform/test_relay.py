from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import sqlalchemy as sa
from src.platform import DomainEvent, OutboxEventBus, OutboxRelay, SubscriberRegistry
from src.platform.extension import STATUS_PUBLISHED, SqlOutboxRepository
from src.platform.extension.sql import OutboxRecord


def _event(name="counter.Incremented", count=1):
    ev = DomainEvent(event_type=name, occurred_at=datetime.now(UTC))
    object.__setattr__(ev, "payload", lambda: {"count": count, "aggregate_id": "u1"})
    return ev


async def _seed(db, *, n=1, name="counter.Incremented"):
    bus = OutboxEventBus(db, source_pkg="counter")
    [bus.publish(_event(name=name, count=i + 1)) for i in range(n)]
    await db.commit()


async def test_run_once_dispatches_sync_async_and_skips_published(db):
    registry, sync_seen, async_seen = SubscriberRegistry(), [], []

    async def async_handler(e: DomainEvent) -> None:
        async_seen.append(e.payload()["count"])

    registry.subscribe("counter.Incremented", lambda e: sync_seen.append(e.payload()["count"]))
    registry.subscribe("counter.Incremented", async_handler)
    await _seed(db, n=2)
    relay = OutboxRelay(registry)
    assert await relay.run_once(db) == 2 and await relay.run_once(db) == 0
    assert (sync_seen, async_seen) == ([1, 2], [1, 2])
    rows = (await db.execute(sa.select(OutboxRecord).order_by(OutboxRecord.id))).scalars().all()
    assert all(r.status == STATUS_PUBLISHED and r.published_at is not None for r in rows)


async def test_redelivery_of_pending_is_idempotent_safe(db):
    registry, applied, events = SubscriberRegistry(), set(), []
    registry.subscribe("counter.Incremented", lambda e: (events.append(e.event_type), applied.add(e.payload()["aggregate_id"])))
    await _seed(db, n=1)
    repo = SqlOutboxRepository(db)
    for _ in range(2):
        for row in await repo.fetch_pending(limit=10):
            ev = DomainEvent(event_type=row.event_type, occurred_at=row.occurred_at)
            object.__setattr__(ev, "payload", lambda r=row: dict(r.payload))
            [handler(ev) for handler in registry.handlers_for(row.event_type)]
    assert len(events) == 2 and applied == {"u1"}


async def test_composition_root_dispatcher_polls_run_once_and_survives_a_failing_pass(monkeypatch):
    import src.main as main_module

    stop_event, passes = asyncio.Event(), []

    class _FlakyRelay:
        async def run_once(self, session) -> int:
            passes.append(1)
            if len(passes) == 1:
                raise RuntimeError("first pass fails")
            stop_event.set()
            return 0

    monkeypatch.setattr(main_module, "outbox_relay", _FlakyRelay())
    monkeypatch.setattr(main_module, "OUTBOX_RELAY_POLL_SECONDS", 0.01)
    await asyncio.wait_for(main_module.run_outbox_relay(stop_event), timeout=5)
    assert len(passes) == 2
