"""DB-backed atomicity of the transactional outbox (AC-platform.1.1).

The single invariant the pattern rests on: a domain event row is written in the
SAME transaction as the domain state change. So a transaction that publishes an
event then ROLLS BACK leaves NO outbox row, and a committed one leaves exactly
the rows it published. Both halves are proven here against a real Postgres
session.
"""

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from common.testing.ac_proof import ac_proof

from src.platform import DomainEvent, OutboxEventBus
from src.platform.extension import STATUS_PENDING
from src.platform.extension.sql import OutboxRecord


def _event(name: str = "test.Thing") -> DomainEvent:
    return DomainEvent(event_type=name, occurred_at=datetime.now(UTC))


async def _outbox_count(db) -> int:
    result = await db.execute(sa.select(sa.func.count()).select_from(OutboxRecord))
    return int(result.scalar_one())


@ac_proof(proof_id="test_outbox_commit_persists_row", ac_ids=["AC-platform.1.1"], ci_tier="pr_ci")
@pytest.mark.asyncio
async def test_commit_leaves_exactly_one_outbox_row(db):
    """AC-platform.1.1: a committed publish leaves exactly one pending outbox row."""
    bus = OutboxEventBus(db, source_pkg="test")
    bus.publish(_event())
    await db.commit()

    assert await _outbox_count(db) == 1
    row = (await db.execute(sa.select(OutboxRecord))).scalar_one()
    assert row.status == STATUS_PENDING
    assert row.event_type == "test.Thing"
    assert row.source_pkg == "test"
    assert row.published_at is None


@ac_proof(proof_id="test_outbox_rollback_leaves_no_row", ac_ids=["AC-platform.1.1"], ci_tier="pr_ci")
@pytest.mark.asyncio
async def test_rollback_leaves_no_outbox_row(db):
    """AC-platform.1.1: a rolled-back publish leaves NO outbox row (atomic)."""
    bus = OutboxEventBus(db, source_pkg="test")
    bus.publish(_event())
    await db.flush()  # row is in the transaction...
    await db.rollback()  # ...but the transaction is abandoned

    assert await _outbox_count(db) == 0
