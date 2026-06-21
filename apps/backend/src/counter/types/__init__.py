"""Counter domain types (nouns) — the package's value language.

These types know nothing about persistence or transport: no ORM, no session, no
HTTP. They are the self-owned SSOT vocabulary (``CounterKey``/``Count``) plus the
published domain event (``Incremented``) and the typed errors.
"""

from __future__ import annotations

from src.counter.types.count import Count
from src.counter.types.errors import (
    CounterError,
    InvalidCounterKeyError,
    NegativeCountError,
)
from src.counter.types.events import Incremented
from src.counter.types.key import CounterKey

__all__ = [
    "Count",
    "CounterError",
    "CounterKey",
    "Incremented",
    "InvalidCounterKeyError",
    "NegativeCountError",
]
