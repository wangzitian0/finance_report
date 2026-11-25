from datetime import UTC, datetime

import sqlalchemy as sa
from src.platform import DomainEvent, OutboxEventBus
from src.platform.extension import STATUS_PENDING
from src.platform.extension.sql import OutboxRecord


def _event(name="test.Thing"):
    return DomainEvent(event_type=name, occurred_at=datetime.now(UTC))


async def _outbox_count(db) -> int:
    return int((await db.execute(sa.select(sa.func.count()).select_from(OutboxRecord))).scalar_one())


async def test_commit_and_rollback_outbox_atomicity(db):
    bus = OutboxEventBus(db, source_pkg="test")
    bus.publish(_event())
    await db.flush()
    await db.rollback()
    assert await _outbox_count(db) == 0

    bus.publish(_event())
    await db.commit()
    assert await _outbox_count(db) == 1
    row = (await db.execute(sa.select(OutboxRecord))).scalar_one()
    assert (row.status, row.event_type, row.source_pkg, row.published_at) == (
        STATUS_PENDING,
        "test.Thing",
        "test",
        None,
    )
