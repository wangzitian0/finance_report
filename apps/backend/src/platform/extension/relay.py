"""``OutboxRelay`` — drains committed outbox rows and dispatches to handlers.

The relay is the *post-commit* half of the transactional outbox (an ``extension``
adapter). It reads ``pending`` rows in enqueue (id) order through the SQL outbox
adapter, reconstructs each into a :class:`DomainEvent`, invokes every handler
subscribed to that ``event_type``, then marks the row ``published``. Because it
only ever reads rows that another transaction already committed, dispatch is
guaranteed to happen *after* the domain state change is durable.

Delivery is **at-least-once**: if the process dies after a handler runs but
before ``mark_published`` commits, the row stays ``pending`` and is redelivered
on the next pass. Therefore **handlers MUST be idempotent** — processing the same
event twice must be a no-op the second time (e.g. key side effects by the event's
aggregate id / a dedupe key). ``run_once`` makes one pass; ``run_forever`` polls
in a loop. Neither is wired as an always-on worker here — see ``readme.md`` for
how it would run (a periodic background task / scheduled job).
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.platform.base.bus import SubscriberRegistry
from src.platform.base.event import DomainEvent
from src.platform.extension.sql import OutboxRecord, SqlOutboxRepository


class _StoredEvent(DomainEvent):
    """A :class:`DomainEvent` reconstructed from a persisted outbox row.

    Carries the row's ``payload`` so a handler reads the event's fields via
    :meth:`payload`, exactly as it would for the original typed event. The relay
    dispatches these (rather than re-instantiating the producer's concrete
    subclass) so it stays ignorant of every producing package's types — the bus
    transports opaque events.
    """

    _payload: dict

    def __init__(self, *, event_type: str, occurred_at: datetime, payload: dict) -> None:
        super().__init__(event_type=event_type, occurred_at=occurred_at)
        object.__setattr__(self, "_payload", payload)

    def payload(self) -> dict:
        return dict(self._payload)


def _to_event(row: OutboxRecord) -> DomainEvent:
    """Rehydrate a persisted outbox row into a dispatchable domain event."""
    return _StoredEvent(
        event_type=row.event_type,
        occurred_at=row.occurred_at,
        payload=dict(row.payload or {}),
    )


class OutboxRelay:
    """Reads committed ``pending`` rows and dispatches them to subscribers."""

    def __init__(self, registry: SubscriberRegistry, *, batch_size: int = 100) -> None:
        self._registry = registry
        self._batch_size = batch_size

    async def run_once(self, session: AsyncSession) -> int:
        """Dispatch one batch of pending rows; return how many were published.

        For each pending row (in id order) every subscribed handler is invoked
        with the reconstructed event, then the row is marked ``published`` and the
        batch is committed. A row with no subscribers is still marked published
        (it has been "delivered" to its — empty — audience), so it is not
        redelivered forever. The marking commit is what makes a second
        ``run_once`` skip already-published rows.
        """
        repo = SqlOutboxRepository(session)
        rows = await repo.fetch_pending(limit=self._batch_size)
        published = 0
        try:
            for row in rows:
                event = _to_event(row)
                for handler in self._registry.handlers_for(row.event_type):
                    # Handlers may be sync or async (EventHandler admits both);
                    # an async handler's work must complete before the row is
                    # marked published, so its awaitable is awaited here.
                    result = handler(event)
                    if inspect.isawaitable(result):
                        await result
                await repo.mark_published(row, published_at=datetime.now(UTC))
                published += 1
        except Exception:
            # A handler (or a mark) raised mid-batch: abandon the partially
            # updated transaction so the caller is never left in a failed-txn
            # state and no half-marked rows can be committed later. The still-
            # pending rows are redelivered on the next pass (at-least-once).
            await session.rollback()
            raise
        if published:
            await session.commit()
        return published

    async def run_forever(
        self,
        session_factory: Callable[[], Awaitable[AsyncSession]] | Callable[[], AsyncSession],
        *,
        poll_interval: float = 1.0,
        stop: Callable[[], bool] | None = None,
    ) -> None:  # pragma: no cover - long-running loop documented, not unit-run
        """Poll the outbox forever, draining each batch then sleeping.

        This is the *shape* of a durable worker, not a wired one: a caller would
        run it as a background task / periodic job (see ``readme.md``). It opens a
        fresh session per pass via ``session_factory`` and sleeps ``poll_interval``
        seconds between passes; ``stop`` lets a supervisor break the loop.
        """
        while not (stop and stop()):
            maybe_session = session_factory()
            session = await maybe_session if hasattr(maybe_session, "__await__") else maybe_session
            try:
                drained = await self.run_once(session)
            finally:
                await session.close()
            if drained == 0:
                await asyncio.sleep(poll_interval)
