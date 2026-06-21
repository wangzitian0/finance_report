"""``increment`` — the counter's write verb (an edge in the project DAG).

Bumps the per-(user, key) tally through the :class:`CounterRepository` port and
returns the new per-user :class:`Count`. It also *publishes* the
:class:`Incremented` domain event: a fact other contexts (e.g. insight-report
generation) can react to. The event is delivered to an optional ``emit`` sink so
the verb stays pure and DB-free — the port is the only collaborator, which is
what makes the op unit-testable with an in-memory fake.

Counting is per (user, key): ``increment`` only ever moves *this user's* tally.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from src.counter.store.repository import CounterRepository
from src.counter.types.count import Count
from src.counter.types.events import Incremented
from src.counter.types.key import CounterKey


def increment(
    repo: CounterRepository,
    *,
    user_id: UUID,
    key: CounterKey,
    emit: Callable[[Incremented], None] | None = None,
    now: datetime | None = None,
) -> Count:
    """Bump (``user_id``, ``key``) by one; emit ``Incremented``; return the new count."""
    new_value = repo.bump(user_id, key)
    count = Count(new_value)
    if emit is not None:
        emit(Incremented(user_id=user_id, key=key, at=now or datetime.now(UTC)))
    return count
