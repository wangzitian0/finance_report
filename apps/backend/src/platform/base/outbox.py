"""The outbox repository *port* (the ``base`` half of the persistence split).

Dependency inversion, mechanism B: the abstract persistence contract the bus and
relay depend on lives here in ``base``; its concrete SQLAlchemy adapter
(:class:`~src.platform.extension.sql.SqlOutboxRepository`, against the shared
:class:`~src.platform.extension.sql.OutboxRecord` table) lives in ``extension`` and
depends back on this port. This keeps ``base`` pure: it speaks plain primitives
and a structural :class:`OutboxRow`, never the ORM/session.

The transactional-outbox pattern hangs on one invariant: a domain event row is
``enqueue``d in the *same* DB transaction as the domain state change (the caller
owns the commit). The relay later ``fetch_pending``s committed rows in id order,
dispatches them, and ``mark_published``es each — so dispatch is inherently
post-commit and at-least-once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Outbox:
    """Public, persistence-neutral description of one enqueued domain event."""

    occurred_at: datetime
    event_type: str
    source_pkg: str
    payload: dict
    aggregate_id: str | None = None
    id: int | None = None
    status: str = "pending"
    published_at: datetime | None = None


class OutboxRow(Protocol):
    """The structural shape of a persisted outbox row the relay reads back.

    The concrete adapter returns its ORM rows, which satisfy this protocol; the
    relay only ever reads these attributes (and hands the row back to
    ``mark_published``), so it never depends on the ORM type itself.
    """

    id: int
    occurred_at: datetime
    event_type: str
    payload: dict | None


class OutboxRepository(Protocol):
    """Session-bound persistence for outbox rows (the port the core depends on).

    An implementation is bound to one session: ``enqueue`` shares the caller's
    transaction (atomic with the domain write — no commit here), while the
    relay's ``fetch_pending``/``mark_published`` run in the relay's own session.
    """

    def enqueue(
        self,
        *,
        occurred_at: datetime,
        event_type: str,
        source_pkg: str,
        payload: dict,
        aggregate_id: str | None = None,
    ) -> OutboxRow:
        """Add a ``pending`` outbox row to the session (no commit)."""
        ...

    async def fetch_pending(self, *, limit: int) -> list[OutboxRow]:
        """Return up to ``limit`` ``pending`` rows in id (enqueue) order."""
        ...

    async def mark_published(self, row: OutboxRow, *, published_at: datetime) -> None:
        """Flip a row to ``published`` and stamp ``published_at`` (no commit)."""
        ...
