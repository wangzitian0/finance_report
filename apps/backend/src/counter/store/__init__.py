"""Counter persistence — the port and its SQLAlchemy adapter.

``CounterRepository`` (the port) is the published storage contract; ops depend on
it. ``SqlCounterRepository`` / ``CounterTally`` are the concrete adapter and are
internal to this role — only the port is part of the package's public language.
"""

from __future__ import annotations

from src.counter.store.repository import CounterRepository
from src.counter.store.sql import CounterTally, SqlCounterRepository

__all__ = ["CounterRepository", "CounterTally", "SqlCounterRepository"]
