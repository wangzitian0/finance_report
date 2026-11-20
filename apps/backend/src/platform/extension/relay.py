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
aggregate id / a dedupe key). ``run_once`` makes one pass; the app composition
root (``main.py``) polls it in the always-on dispatcher loop — see ``readme.md``.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from src.platform.base.bus import SubscriberRegistry
from src.platform.base.event import DomainEvent
from src.platform.base.outbox import OutboxRow
from src.platform.extension.sql import SqlOutboxRepository


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


def _to_event(row: OutboxRow) -> DomainEvent:
    """Rehydrate a persisted outbox row into a dispatchable domain event."""
    return _StoredEvent(
        event_type=row.event_type,
        occurred_at=row.occurred_at,
        payload=dict(row.payload or {}),
    )


class OutboxRelay:
    """Reads committed ``pending`` rows and dispatches them to subscribers."""

    def __init__(
        self,
        registry: SubscriberRegistry,
        *,
        batch_size: int = 100,
        max_attempts: int = 5,
        on_dead_letter: Callable[[str, str], None] | None = None,
    ) -> None:
        self._registry = registry
        self._batch_size = batch_size
        self._max_attempts = max(1, max_attempts)
        self._on_dead_letter = on_dead_letter

    async def run_once(self, session: AsyncSession) -> int:
        """Dispatch pending rows in savepoints; dead-letter exhausted failures."""
        repo = SqlOutboxRepository(session)
        rows = await repo.fetch_pending(limit=self._batch_size)
        published = 0
        mutated = False
        dead_letters: list[tuple[str, str]] = []
        for row in rows:
            outbox_row = cast(OutboxRow, row)
            event = _to_event(outbox_row)
            event_type = row.event_type
            source_pkg = row.source_pkg
            try:
                async with session.begin_nested():
                    for handler in self._registry.handlers_for(event_type):
                        # Handlers may be sync or async (EventHandler admits both);
                        # an async handler's work must complete before the row is
                        # marked published, so its awaitable is awaited here.
                        result = handler(event)
                        if inspect.isawaitable(result):
                            await result
                    await repo.mark_published(row, published_at=datetime.now(UTC))
                published += 1
                mutated = True
            except Exception as exc:
                error_text = f"{type(exc).__name__}: {exc}"
                moved = await repo.record_failure(
                    row,
                    error=error_text,
                    max_attempts=self._max_attempts,
                )
                mutated = True
                if moved and self._on_dead_letter is not None:
                    dead_letters.append((event_type, source_pkg))
        if mutated:
            await session.commit()
            for event_type, source_pkg in dead_letters:
                if self._on_dead_letter is not None:
                    self._on_dead_letter(event_type, source_pkg)
        return published
