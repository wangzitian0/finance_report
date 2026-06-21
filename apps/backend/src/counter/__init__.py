"""``counter`` — a per-(user, key) tally package (platform class, first worked example).

This is the first instance of the repo's **package = DDD bounded context** model:
a README (prose / ubiquitous language) + a :class:`PackageContract` in
``contract.py`` + role folders that converge by role, and a *published language*
declared here in ``__all__``.

Ubiquitous language:
- **Key** — a namespaced counter identity (lowercase dotted ``domain.action``,
  validated; the package's self-owned SSOT term).
- **Count** — a non-negative tally ("how many times did X happen").
- counting is **per (user, key)**; a query returns either the per-user count or
  the **global** count (sum across users), which feeds insight-report generation.

Roles (files converge by role):
- ``types/``  domain nouns + events — ``CounterKey``/``Count``/``Incremented``;
- ``ops/``    domain verbs — ``increment`` / ``get_count`` over the store *port*;
- ``store/``  persistence — ``CounterRepository`` (port) + the SQL adapter;
- ``api/``    boundary — the thin async ``read_count`` for reporting.

Dependency rule (keeps the project a DAG): ``api → ops → {types, store}``; the
ORM/session lives only in ``store``/``api`` and never leaks into ``types``/``ops``.
Only the names below are public; everything else (the SQL adapter, the table
model) is internal.
"""

from __future__ import annotations

from src.counter.api import read_count
from src.counter.ops import get_count, increment
from src.counter.store import CounterRepository
from src.counter.types import (
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
    "read_count",
]
