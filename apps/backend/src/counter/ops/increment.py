"""``increment`` — the counter's write verb (an edge in the project DAG).

Bumps the per-(user, key) tally through the :class:`CounterRepository` port and
returns the new per-user :class:`Count`. It also *publishes* the
:class:`Incremented` domain event through the platform :class:`EventBus`: a fact
other contexts (e.g. insight-report generation) can react to.

The bus is the only new collaborator and it is optional, so the verb stays
unit-testable with an in-memory fake repo + a :class:`RecordingEventBus`. In
production the caller passes an :class:`OutboxEventBus` built from the *same*
``AsyncSession`` the repo writes through, so the ``Incremented`` outbox row is
INSERTed in the same transaction as the tally bump — atomic by construction
(rollback ⇒ no outbox row; commit ⇒ exactly one). Publishing only *enqueues* the
event; the relay dispatches it post-commit.

Counting is per (user, key): ``increment`` only ever moves *this user's* tally.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from src.counter.store.repository import CounterRepository
from src.counter.types.count import Count
from src.counter.types.events import Incremented
from src.counter.types.key import CounterKey
from src.platform.events.bus import EventBus


def increment(
    repo: CounterRepository,
    *,
    user_id: UUID,
    key: CounterKey,
    bus: EventBus | None = None,
    now: datetime | None = None,
) -> Count:
    """Bump (``user_id``, ``key``) by one; publish ``Incremented``; return the new count."""
    new_value = repo.bump(user_id, key)
    count = Count(new_value)
    if bus is not None:
        bus.publish(
            Incremented.create(
                user_id=user_id,
                key=key,
                count=new_value,
                at=now or datetime.now(UTC),
            )
        )
    return count
