"""``ledger.base`` — the pure double-entry core (types + validators).

No I/O and no concrete cross-package wiring: it never imports this package's own
``extension`` / ``data`` layers, and reaches other packages only through their
published interfaces (``src.audit.money``'s value types, ``src.config`` as a bare module).
"""

from __future__ import annotations

from src.ledger.base.decision_anchor import DecisionAnchor, DecisionAnchorError, journal_command_target
from src.ledger.base.processing import (
    ProcessingAccount,
    ProcessingCurrencyConflictError,
    TransferAccountCurrencyMismatchError,
    TransferPair,
    detect_transfer_pattern,
)
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
    "DecisionAnchor",
    "DecisionAnchorError",
    "journal_command_target",
    "Entry",
    "LedgerError",
    "Leg",
    "ProcessingAccount",
    "ProcessingCurrencyConflictError",
    "TransferAccountCurrencyMismatchError",
    "TransferPair",
    "UnbalancedEntryError",
    "ValidationError",
    "detect_transfer_pattern",
    "validate_fx_rates",
    "validate_journal_balance",
    "validate_journal_posting_invariants",
]
