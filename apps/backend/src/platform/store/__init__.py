"""Platform persistence — the shared outbox table and its repository.

``Outbox`` is the single shared ORM table every producer enqueues into;
``OutboxRepository`` is the thin session-bound data access the bus and relay use.
This is the only role that touches the ORM/session.
"""

from __future__ import annotations

from src.platform.store.outbox import Outbox, OutboxRepository

__all__ = ["Outbox", "OutboxRepository"]
