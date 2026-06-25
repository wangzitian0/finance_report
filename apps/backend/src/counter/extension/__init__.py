"""``counter.extension`` — the impure edges: the ORM adapter + the async boundary.

Depends on ``src.database`` (ORM) and the ``platform`` event bus/outbox. This is
where the package reaches across to other packages and to I/O; the ``base`` layer
stays pure behind the ports this layer satisfies.
"""

from __future__ import annotations

from src.counter.extension.api import read_count, record_increment
from src.counter.extension.sql import CounterTally, SqlCounterRepository

__all__ = ["CounterTally", "SqlCounterRepository", "read_count", "record_increment"]
