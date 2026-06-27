"""``DomainEvent`` — the base value type for every event on the bus.

A domain event is an immutable record of a fact that already happened. It is the
*published language* a bounded context emits so other contexts can react without
importing its internals. Two pieces of identity are universal to every event and
therefore live on this base:

- ``event_type`` — a stable, namespaced ``"<pkg>.<Name>"`` string (e.g.
  ``"counter.Incremented"``); the routing key the bus and relay dispatch on.
- ``occurred_at`` — when the fact happened (timezone-aware UTC).

Subclasses add their own fields and override :meth:`payload` to expose them as a
JSON-serializable mapping (the shape persisted into the outbox ``payload`` jsonb
column). The base is frozen: an event is a fact, not a mutable record.

This module is the leaf of the ``platform`` package's ``base`` layer — it imports
nothing from the app (no ORM, no session), so every layer above (the ``base``
ports, the ``extension`` adapters, and every consumer package) may build events
on top of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DomainEvent:
    """An immutable fact: ``event_type`` happened at ``occurred_at`` (UTC).

    Subclasses set their ``event_type`` (a namespaced ``"<pkg>.<Name>"`` literal)
    and add fields; they override :meth:`payload` to serialize those fields into
    the JSON object persisted in the outbox. The base ``payload`` carries no
    subclass fields, so a subclass that adds state MUST override it.
    """

    event_type: str
    occurred_at: datetime

    def payload(self) -> dict:
        """JSON-serializable body persisted to the outbox ``payload`` column.

        The base returns an empty mapping (``event_type``/``occurred_at`` are
        stored in their own outbox columns, not the payload). A subclass that
        adds fields overrides this to expose them; the relay reconstructs the
        event from ``event_type`` + ``occurred_at`` + ``payload`` on dispatch.
        """
        return {}
