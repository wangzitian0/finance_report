"""``ledger.base`` — the pure double-entry core (types + validators + the port).

No I/O and no concrete cross-package wiring: it never imports this package's own
``extension`` / ``data`` layers, and reaches other packages only through their
published interfaces (``src.audit.money``'s value types, ``src.config`` as a bare module).
The :class:`JournalRepository` is a *port* (a Protocol) satisfied by the
``extension`` adapter — mechanism B (dependency inversion).
"""

from __future__ import annotations

from src.ledger.base.processing import (
    ProcessingAccount,
    TransferPair,
    detect_transfer_pattern,
)
from src.ledger.base.repository import JournalRepository
from src.ledger.base.types import (
    DegenerateEntryError,
    Entry,
    LedgerError,
    Leg,
    UnbalancedEntryError,
)
from src.ledger.base.validators import (
    AccountingError,
    ValidationError,
    validate_fx_rates,
    validate_journal_balance,
    validate_journal_posting_invariants,
)

__all__ = [
    "AccountingError",
    "DegenerateEntryError",
    "Entry",
    "JournalRepository",
    "LedgerError",
    "Leg",
    "ProcessingAccount",
    "TransferPair",
    "UnbalancedEntryError",
    "ValidationError",
    "detect_transfer_pattern",
    "validate_fx_rates",
    "validate_journal_balance",
    "validate_journal_posting_invariants",
]
