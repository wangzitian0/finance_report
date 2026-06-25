"""``Count`` — a non-negative tally value object.

A count answers "how many times did X happen". It is non-negative by
construction: a negative tally is meaningless, so :class:`NegativeCountError` is
raised rather than allowing an invalid value to flow into a report.

A count is a frozen value object that behaves like its underlying ``int`` for
comparison/formatting, but it is its own type so a raw ``int`` from the store is
narrowed to a validated tally at the package boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.counter.base.types.errors import NegativeCountError


@dataclass(frozen=True, order=True)
class Count:
    """A non-negative integer tally (cannot be constructed negative)."""

    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise NegativeCountError(f"count must be a non-bool int, got {type(self.value).__name__}")
        if self.value < 0:
            raise NegativeCountError(f"count must be non-negative, got {self.value}")

    def __int__(self) -> int:
        return self.value

    def __str__(self) -> str:
        return str(self.value)
