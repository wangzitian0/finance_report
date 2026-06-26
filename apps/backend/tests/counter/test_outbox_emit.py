"""counter emits ``counter.Incremented`` through the outbox (AC-platform.1.5).

Proves the package wiring end to end against a real Postgres session: the async
``record_increment`` boundary bumps the per-(user, key) tally AND writes the
``counter.Incremented`` event into the shared outbox in the SAME transaction. A
committed increment leaves exactly one matching outbox row; a rolled-back one
leaves neither the tally nor the event — atomicity carried through the package.
"""

from uuid import uuid4

import pytest
import sqlalchemy as sa
from common.testing.ac_proof import ac_proof

from src.counter import CounterKey, increment, read_count, record_increment
from src.counter.base.types.events import EVENT_TYPE
from src.platform import Outbox, RecordingEventBus
from src.platform.extension.sql import STATUS_PENDING

KEY = CounterKey("report.generated")


async def _outbox_rows(db):
    return (await db.execute(sa.select(Outbox).order_by(Outbox.id))).scalars().all()


@ac_proof(proof_id="test_counter_emits_to_outbox", ac_ids=["AC-platform.1.5"], ci_tier="pr_ci")
@pytest.mark.asyncio
async def test_record_increment_writes_incremented_atomically(db):
    """AC-platform.1.5: record_increment bumps the tally and enqueues counter.Incremented."""
    user_id = uuid4()

    count = await record_increment(db, user_id=user_id, key=KEY)
    await db.commit()

    assert int(count) == 1
    assert int(await read_count(db, key=KEY, user_id=user_id)) == 1

    rows = await _outbox_rows(db)
    assert len(rows) == 1
    row = rows[0]
    assert row.event_type == EVENT_TYPE  # "counter.Incremented"
    assert row.source_pkg == "counter"
    assert row.status == STATUS_PENDING
    assert row.payload["user_id"] == str(user_id)
    assert row.payload["key"] == KEY.value
    assert row.payload["count"] == 1


@ac_proof(proof_id="test_counter_emit_rolls_back_with_tally", ac_ids=["AC-platform.1.5"], ci_tier="pr_ci")
@pytest.mark.asyncio
async def test_rollback_leaves_neither_tally_nor_event(db):
    """AC-platform.1.5: rollback ⇒ no tally bump AND no outbox row (one transaction)."""
    user_id = uuid4()

    await record_increment(db, user_id=user_id, key=KEY)
    await db.flush()
    await db.rollback()

    assert int(await read_count(db, key=KEY, user_id=user_id)) == 0
    assert len(await _outbox_rows(db)) == 0


@ac_proof(proof_id="test_counter_increment_op_publishes_via_bus", ac_ids=["AC-platform.1.5"], ci_tier="pr_ci")
def test_increment_op_publishes_through_bus_fake():
    """AC-platform.1.5: the pure increment verb publishes Incremented through any EventBus."""
    from tests.counter._fake import InMemoryCounterRepository

    repo = InMemoryCounterRepository()
    bus = RecordingEventBus()
    user_id = uuid4()

    increment(repo, user_id=user_id, key=KEY, bus=bus)

    assert len(bus.published) == 1
    event = bus.published[0]
    assert event.event_type == EVENT_TYPE
    assert event.payload()["count"] == 1
