from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.platform import DomainEvent, OutboxEventBus, OutboxRelay, SubscriberRegistry
from src.platform.extension import STATUS_FAILED, STATUS_PENDING, STATUS_PUBLISHED, SqlOutboxRepository
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
    registry.subscribe(
        "counter.Incremented", lambda e: (events.append(e.event_type), applied.add(e.payload()["aggregate_id"]))
    )
    await _seed(db, n=1)
    repo = SqlOutboxRepository(db)
    for _ in range(2):
        for row in await repo.fetch_pending(limit=10):
            ev = DomainEvent(event_type=row.event_type, occurred_at=row.occurred_at)
            object.__setattr__(ev, "payload", lambda r=row: dict(r.payload))
            [handler(ev) for handler in registry.handlers_for(row.event_type)]
    assert len(events) == 2 and applied == {"u1"}


async def test_run_once_isolates_poison_pill_via_savepoint_and_marks_failed(db):
    registry, good_seen, dead_letters = SubscriberRegistry(), [], []

    def bad_handler(e: DomainEvent) -> None:
        raise ValueError(f"boom-{e.payload()['count']}")

    registry.subscribe("bad.Event", bad_handler)
    registry.subscribe("good.Event", lambda e: good_seen.append(e.payload()["count"]))

    bus = OutboxEventBus(db, source_pkg="counter")
    bus.publish(_event(name="bad.Event", count=1))
    bus.publish(_event(name="good.Event", count=2))
    await db.commit()

    relay = OutboxRelay(
        registry,
        max_attempts=2,
        on_dead_letter=lambda event_type, source_pkg: dead_letters.append((event_type, source_pkg)),
    )

    # Pass 1: bad row fails (attempt 1 -> stays pending), healthy sibling STILL publishes.
    assert await relay.run_once(db) == 1
    assert good_seen == [2]
    assert dead_letters == []
    rows = (await db.execute(sa.select(OutboxRecord).order_by(OutboxRecord.id))).scalars().all()
    assert (rows[0].status, rows[0].attempt_count) == (STATUS_PENDING, 1)
    assert "boom-1" in (rows[0].last_error or "")
    assert rows[1].status == STATUS_PUBLISHED

    # Pass 2: bad row hits max_attempts=2 -> moves to failed & triggers dead-letter callback.
    assert await relay.run_once(db) == 0
    rows = (await db.execute(sa.select(OutboxRecord).order_by(OutboxRecord.id))).scalars().all()
    assert (rows[0].status, rows[0].attempt_count) == (STATUS_FAILED, 2)
    assert dead_letters == [("bad.Event", "counter")]
    assert await repo_count_pending(db) == 0


async def repo_count_pending(db: AsyncSession) -> int:
    return (await db.execute(sa.select(sa.func.count()).where(OutboxRecord.status == STATUS_PENDING))).scalar_one()


async def test_concurrent_sessions_skip_locked_pending_rows(db_engine):
    maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as seed_session:
        await _seed(seed_session, n=2)

    async with maker() as s1, maker() as s2:
        r1 = SqlOutboxRepository(s1)
        r2 = SqlOutboxRepository(s2)
        locked_1 = await r1.fetch_pending(limit=1)
        locked_2 = await r2.fetch_pending(limit=10)
        assert [row.payload["count"] for row in locked_1] == [1]
        assert [row.payload["count"] for row in locked_2] == [2]
        await s1.rollback()
        await s2.rollback()


async def test_composition_root_run_outbox_relay_uses_real_db_and_survives_error(db_engine, monkeypatch):
    import src.main as main_module

    maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as seed_session:
        await _seed(seed_session, n=1)

    stop_event = asyncio.Event()
    calls = 0
    original_run_once = main_module.outbox_relay.run_once

    async def scripted_run_once(session: AsyncSession) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient relay error")
        count = await original_run_once(session)
        stop_event.set()
        return count

    monkeypatch.setattr(main_module, "async_session_maker", maker)
    monkeypatch.setattr(main_module, "OUTBOX_RELAY_POLL_SECONDS", 0.01)
    monkeypatch.setattr(main_module.outbox_relay, "run_once", scripted_run_once)

    await asyncio.wait_for(main_module.run_outbox_relay(stop_event), timeout=5)
    assert calls == 2
    async with maker() as verify_session:
        rows = (await verify_session.execute(sa.select(OutboxRecord))).scalars().all()
        assert len(rows) == 1 and rows[0].status == STATUS_PUBLISHED
