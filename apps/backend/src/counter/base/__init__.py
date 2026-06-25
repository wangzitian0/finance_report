"""``counter.base`` — the pure, self-contained core (types + ops + the store port).

No I/O and no concrete cross-package wiring: imports only other packages' ``base``
(e.g. ``platform`` event/bus ports). The EventBus and repository are *ports*
(Protocols) injected by the ``extension`` layer.
"""

from __future__ import annotations

from src.counter.base.ops import get_count, increment
from src.counter.base.repository import CounterRepository
from src.counter.base.types import (
    Count,
    CounterError,
    CounterKey,
    Incremented,
    InvalidCounterKeyError,
    NegativeCountError,
)

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
]
