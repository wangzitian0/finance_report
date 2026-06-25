"""``counter`` — per-(user, key) tallies (platform package).

Layers (see common/meta/migration-standard.md): ``base`` (pure types/ops + the
store port) and ``extension`` (the ORM adapter + async outbox boundary). The
published language below (``__all__``) must equal ``contract.interface``.
"""

from __future__ import annotations

from src.counter.base import (
    Count,
    CounterError,
    CounterKey,
    CounterRepository,
    Incremented,
    InvalidCounterKeyError,
    NegativeCountError,
    get_count,
    increment,
)
from src.counter.extension import read_count, record_increment

__all__ = [
    "Count",
    "CounterError",
    "CounterKey",
    "CounterRepository",
    "Incremented",
    "InvalidCounterKeyError",
    "NegativeCountError",
    "get_count",
    "increment",
    "read_count",
    "record_increment",
]
