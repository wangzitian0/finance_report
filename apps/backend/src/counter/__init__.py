"""``counter`` — the backend implementation of the ``counter`` package.

This is ``PackageContract.implementations["be"]``; the package's authoritative
spec (ubiquitous language, contract, roles, storage, governance) lives in
``common/counter/`` (``readme.md`` + ``contract.py``). See
``common/governance/readme.md`` for the package model.

Files converge by role — ``types`` (nouns + events), ``ops`` (verbs over the
store port), ``store`` (the ``CounterRepository`` port + SQL adapter), ``api``
(the thin async ``read_count`` boundary) — with the DAG ``api → ops → {types,
store}``. The names re-exported below are the *entire* public surface
(``__all__`` must equal ``contract.interface``); everything else is internal.
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
