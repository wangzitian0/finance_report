"""``ledger`` — the double-entry domain module (vertical slice).

Roles converge by folder: ``types/`` (nouns: ``Entry``/``Leg`` — the balance
invariant), ``ops/`` (verbs: ``post_entry``). Persistence (``models.journal`` /
``services.accounting``) and API (``routers``/``schemas.journal``) are the
``store``/``api`` roles, kept in place for now (their physical relocation is
downstream-owned structure, not a proof-quality gain — see vision).

Dependency rule: ``ops → {types, store} → kernel`` (``src.money`` etc.); never
upward.

The public surface is exposed **lazily** via ``__getattr__`` so a module in the
``store`` layer (e.g. ``services.accounting``, ``services.fx_revaluation``) can
``from src.ledger import Entry, Leg`` to use the balance invariant **without**
eagerly pulling in ``ops`` — which imports ``services.accounting`` and would form
a cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
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

_TYPE_NAMES = {
    "Entry",
    "Leg",
    "LedgerError",
    "UnbalancedEntryError",
    "DegenerateEntryError",
}


def __getattr__(name: str):
    if name in _TYPE_NAMES:
        from . import types

        value = getattr(types, name)
    elif name == "post_entry":
        from .ops import post_entry as value
    else:
        raise AttributeError(f"module 'src.ledger' has no attribute {name!r}")
    # Cache so subsequent attribute access skips the re-import (consistent with
    # the lazy-__getattr__ pattern in src.services.__init__).
    globals()[name] = value
    return value
