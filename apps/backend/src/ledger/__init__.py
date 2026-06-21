"""``ledger`` — the double-entry domain module (template vertical slice).

This module is the worked example of the project's target shape: a *vertical
domain slice* whose files converge by role —

- ``types/``  domain nouns (``Entry``/``Leg``) — the balance invariant lives here
- ``ops/``    domain verbs (``post_entry``) — the edges in the project DAG
- ``store/``  persistence (currently ``src.models.journal`` / ``services.accounting``;
              to be folded in as the module matures)
- ``api/``    boundary (currently ``src.routers`` + ``src.schemas.journal``)

Dependency rule (keeps the project a DAG): ``api → ops → {types, store} → kernel``
(``src.money`` etc.); never upward. See ``ledger.contract.md``.
"""

from __future__ import annotations

from src.ledger.ops import post_entry
from src.ledger.types import (
    DegenerateEntryError,
    Entry,
    LedgerError,
    Leg,
    UnbalancedEntryError,
)

__all__ = [
    "Entry",
    "DegenerateEntryError",
    "Leg",
    "LedgerError",
    "UnbalancedEntryError",
    "post_entry",
]
