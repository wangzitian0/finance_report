"""``get_count`` — the counter's read verb.

Returns either the per-user count or the GLOBAL count (sum across users) for a
key, as a :class:`Count`. ``user_id=None`` means "overall" — the number that
feeds an insight report's "how many times did X happen, across everyone"; a
concrete ``user_id`` answers "for this user".

Like :func:`increment`, this verb depends only on the
:class:`CounterRepository` port, so it is unit-testable without a database.
"""

from __future__ import annotations

from uuid import UUID

from src.counter.store.repository import CounterRepository
from src.counter.types.count import Count
from src.counter.types.key import CounterKey


def get_count(
    repo: CounterRepository,
    *,
    key: CounterKey,
    user_id: UUID | None = None,
) -> Count:
    """Global count when ``user_id`` is None, else the per-user count."""
    if user_id is None:
        return Count(repo.total(key))
    return Count(repo.for_user(user_id, key))
