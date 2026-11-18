from uuid import uuid4

import sqlalchemy as sa
from src.counter import CounterKey, increment, read_count, record_increment
from src.counter.base.types.events import EVENT_TYPE
from src.platform import RecordingEventBus
from src.platform.extension import STATUS_PENDING
from src.platform.extension.sql import OutboxRecord

from ._fake import InMemoryCounterRepository

KEY = CounterKey("report.generated")


async def _outbox_rows(db):
    return (await db.execute(sa.select(OutboxRecord).order_by(OutboxRecord.id))).scalars().all()


async def test_record_increment_writes_incremented_atomically(db):
    user_id = uuid4()
    count = await record_increment(db, user_id=user_id, key=KEY)
    await db.commit()
    assert int(count) == 1 and int(await read_count(db, key=KEY, user_id=user_id)) == 1
    rows = await _outbox_rows(db)
    assert len(rows) == 1
    row = rows[0]
    assert (row.event_type, row.source_pkg, row.status, row.payload["user_id"], row.payload["key"], row.payload["count"]) == (
        EVENT_TYPE,
        "counter",
        STATUS_PENDING,
        str(user_id),
        KEY.value,
        1,
    )


async def test_rollback_leaves_neither_tally_nor_event(db):
    user_id = uuid4()
    await record_increment(db, user_id=user_id, key=KEY)
    await db.flush()
    await db.rollback()
    assert int(await read_count(db, key=KEY, user_id=user_id)) == 0 and await _outbox_rows(db) == []


async def test_increment_op_publishes_through_bus_fake():
    repo, bus = InMemoryCounterRepository(), RecordingEventBus()
    await increment(repo, user_id=uuid4(), key=KEY, bus=bus)
    assert len(bus.published) == 1 and (bus.published[0].event_type, bus.published[0].payload()["count"]) == (EVENT_TYPE, 1)
