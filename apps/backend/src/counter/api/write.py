"""``record_increment`` — the atomic async write boundary for the counter.

This is the production composition seam: it bumps the per-(user, key) tally AND
enqueues the :class:`Incremented` domain event into the platform outbox **using
the one ``AsyncSession`` the caller holds**, so both land in the same
transaction. The caller commits once: tally upsert + outbox row commit together,
or — on rollback — neither persists. That single-session sharing is what makes
the event atomic with the state change (the heart of the transactional outbox).

``api`` is the only role that combines the session with the domain verbs and with
the platform bus; ``ops.increment`` stays a pure, session-free verb that the
in-memory fake can unit-test. Dispatch is NOT done here — the row is left
``pending`` for the relay to deliver post-commit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.counter.store.sql import SqlCounterRepository
from src.counter.types.count import Count
from src.counter.types.events import Incremented
from src.counter.types.key import CounterKey
from src.platform.events.bus import OutboxEventBus

#: The ``source_pkg`` tag every counter event carries in the shared outbox.
SOURCE_PKG = "counter"


async def record_increment(
    db: AsyncSession,
    *,
    user_id: UUID,
    key: CounterKey,
) -> Count:
    """Atomically bump (``user_id``, ``key``) and enqueue ``Incremented``.

    Performs the async upsert-increment and writes the ``Incremented`` outbox row
    in the same ``db`` session/transaction; the caller owns the commit. Returns
    the new per-user :class:`Count`. Does not commit — atomicity is the caller's
    single ``commit()`` over this session.
    """
    repo = SqlCounterRepository(db)
    new_value = await repo.bump(user_id, key)
    bus = OutboxEventBus(db, source_pkg=SOURCE_PKG)
    bus.publish(Incremented.create(user_id=user_id, key=key, count=new_value, at=_now()))
    return Count(new_value)


def _now() -> datetime:
    """UTC timestamp for the event's ``occurred_at`` (kept tiny + injectable)."""
    return datetime.now(UTC)
