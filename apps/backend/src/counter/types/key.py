"""``CounterKey`` — a namespaced counter identity (the package's SSOT term).

A counter key names *what is being counted*: a lowercase, dotted
``domain.action`` identifier such as ``report.generated`` or
``statement.uploaded``. The shape is the ubiquitous language of the package, so
it is enforced as a type: an invalid key cannot be constructed
(:class:`InvalidCounterKeyError` is raised), exactly like ``Money`` rejects
``float``.

A key is a frozen value object — two keys with the same string are equal and
hashable, so it is a safe dict/identity key in repositories and events.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.counter.types.errors import InvalidCounterKeyError

#: A key is one-or-more lowercase ``[a-z0-9_]`` segments joined by dots, each
#: segment starting with a letter. Non-empty by construction (``+`` on segments).
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


@dataclass(frozen=True)
class CounterKey:
    """A validated, namespaced counter identity (e.g. ``report.generated``)."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise InvalidCounterKeyError(f"counter key must be a str, got {type(self.value).__name__}")
        if not _KEY_PATTERN.match(self.value):
            raise InvalidCounterKeyError(
                f"counter key must be lowercase dotted 'domain.action' (e.g. 'report.generated'), got {self.value!r}"
            )

    def __str__(self) -> str:
        return self.value
