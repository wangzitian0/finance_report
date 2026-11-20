"""The shared outbox table — ORM model + the SQL repository adapter.

This is the ``extension`` (impure) half of the persistence split: the concrete
:class:`SqlOutboxRepository` adapter that satisfies the
:class:`~src.platform.base.outbox.OutboxRepository` port, backed by the shared
:class:`OutboxRecord` ORM table. The only role that touches the ORM/session.

The transactional-outbox pattern hangs on ONE invariant: a domain event row is
INSERTed in the *same* DB transaction as the domain state change that produced
it. Because the write shares the caller's :class:`AsyncSession`, the event and
the state change commit together or roll back together — there is no window where
one persists without the other.

``OutboxRecord`` is the single shared table (owned by the ``platform`` package); every
package that emits through the bus writes its events here, tagged with
``source_pkg``/``event_type``. The relay (``extension/relay.py``) later reads
committed ``pending`` rows in id order and dispatches them, so dispatch is
inherently post-commit. Status moves ``pending -> published`` exactly once the
relay has delivered the row to every subscribed handler.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base

#: The two lifecycle states of an outbox row. ``pending`` is enqueued-and-
#: committed but not yet dispatched; ``published`` is dispatched to every
#: subscriber. Stored as plain text (no ``sa.Enum``) so adding a state later
#: needs no enum migration — the relay only ever queries ``status = 'pending'``.
STATUS_PENDING = "pending"
STATUS_PUBLISHED = "published"
STATUS_FAILED = "failed"


class OutboxRecord(Base):
    """One enqueued domain event awaiting (or having had) relay dispatch.

    The ``(status, id)`` index backs the relay's hot query — "the oldest pending
    rows, in order" — so draining the outbox never scans published history.
    """

    __tablename__ = "outbox"
    __table_args__ = (sa.Index("ix_outbox_status_id", "status", "id"),)

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_pkg: Mapped[str] = mapped_column(sa.Text, nullable=False)
    aggregate_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default=STATUS_PENDING)
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class SqlOutboxRepository:
    """Async SQL adapter for :class:`~src.platform.base.outbox.OutboxRepository`.

    Every method operates on the session it was constructed with — so an
    ``enqueue`` shares the caller's transaction (atomic with the domain write),
    and the relay's reads/marks happen in the relay's own session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def enqueue(
        self,
        *,
        occurred_at: datetime,
        event_type: str,
        source_pkg: str,
        payload: dict,
        aggregate_id: str | None = None,
    ) -> OutboxRecord:
        """Add a ``pending`` outbox row to the session (no commit).

        The row is flushed with the caller's transaction; the caller (the domain
        write) owns the commit, which is what makes the event atomic with the
        state change. Returns the pending row (its ``id`` is assigned on flush).
        """
        row = OutboxRecord(
            occurred_at=occurred_at,
            event_type=event_type,
            source_pkg=source_pkg,
            aggregate_id=aggregate_id,
            payload=payload,
            status=STATUS_PENDING,
            attempt_count=0,
        )
        self._session.add(row)
        return row

    async def fetch_pending(self, *, limit: int) -> list[OutboxRecord]:
        """Return up to ``limit`` ``pending`` rows in id (enqueue) order."""
        result = await self._session.execute(
            sa.select(OutboxRecord)
            .where(OutboxRecord.status == STATUS_PENDING)
            .order_by(OutboxRecord.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def mark_published(self, row: OutboxRecord, *, published_at: datetime) -> None:
        """Flip a row to ``published`` and stamp ``published_at`` (no commit)."""
        row.status = STATUS_PUBLISHED
        row.published_at = published_at
        await self._session.flush()

    async def record_failure(self, row: OutboxRecord, *, error: str, max_attempts: int) -> bool:
        """Increment ``attempt_count`` and move ``row`` to ``failed`` at ``max_attempts``."""
        await self._session.refresh(row)
        attempts = (row.attempt_count or 0) + 1
        row.attempt_count = attempts
        row.last_error = error[:2000]
        moved_to_dead_letter = attempts >= max_attempts
        if moved_to_dead_letter:
            row.status = STATUS_FAILED
        await self._session.flush()
        return moved_to_dead_letter
