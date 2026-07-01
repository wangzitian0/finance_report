"""Quantity unit value type."""

from __future__ import annotations

import re
from dataclasses import dataclass

from common.audit.quantity.errors import InvalidUnitError

_UNIT_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class Unit:
    """A normalized quantity unit such as ``shares`` or ``contracts``."""

    code: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, str):
            raise InvalidUnitError(
                f"unit must be a string, got {type(self.code).__name__}"
            )
        normalized = self.code.strip().lower()
        if not _UNIT_RE.fullmatch(normalized):
            raise InvalidUnitError(f"invalid quantity unit: {self.code!r}")
        object.__setattr__(self, "code", normalized)

    @classmethod
    def of(cls, value: Unit | str) -> Unit:
        if isinstance(value, Unit):
            return value
        return cls(value)

    def __str__(self) -> str:
        return self.code
