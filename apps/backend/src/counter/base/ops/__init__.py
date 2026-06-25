"""Counter domain operations (verbs).

``increment`` (write, emits ``Incremented``) and ``get_count`` (read,
per-user or global). Both depend only on the ``CounterRepository`` port and the
domain types — never on the ORM/session — so they are the package's pure,
unit-testable verbs.
"""

from __future__ import annotations

from src.counter.base.ops.increment import increment
from src.counter.base.ops.query import get_count

__all__ = ["get_count", "increment"]
