"""``Incremented`` — the counter domain event (published language).

A package's *events* are part of its published interface: other contexts react
to ``Incremented`` (e.g. insight-report generation) without importing the
counter store or ops. The event is an immutable record of a fact that already
happened — a per-(user, key) tally was bumped at ``at``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.counter.types.key import CounterKey


@dataclass(frozen=True)
class Incremented:
    """A fact: ``user_id``'s tally for ``key`` was incremented at ``at``."""

    user_id: UUID
    key: CounterKey
    at: datetime
