"""``read_count`` — the in-process boundary verb for insight-report generation.

This is the one thin, async read the package exposes for callers that hold an
``AsyncSession``: it awaits the SQL adapter and returns a validated
:class:`Count`. Reporting asks "how many times did X happen — overall, or for
this user" by calling this with ``user_id=None`` (global) or a concrete user.

We keep ``api`` deliberately minimal: the package's primary published language is
the in-process verbs (``increment`` / ``get_count``) over the
:class:`CounterRepository` port; no HTTP route is added until a transport need is
real. ``api`` is the only place the async session meets the domain verbs.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.counter.base.types.count import Count
from src.counter.base.types.key import CounterKey
from src.counter.extension.sql import SqlCounterRepository


async def read_count(
    db: AsyncSession,
    *,
    key: CounterKey,
    user_id: UUID | None = None,
) -> Count:
    """Read the global (``user_id=None``) or per-user tally for ``key``."""
    repo = SqlCounterRepository(db)
    if user_id is None:
        return Count(await repo.total(key))
    return Count(await repo.for_user(user_id, key))
