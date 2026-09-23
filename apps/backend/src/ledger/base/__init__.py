"""``ledger.base`` — the pure double-entry core (types, vocabulary + validators).

No I/O and no concrete cross-package wiring: it never imports this package's own
``extension`` / ``data`` layers, has zero ORM or configuration dependencies, and reaches other
packages only through their published pure value interfaces (``src.audit.money``).
"""

from __future__ import annotations

from src.ledger.base.contribution import JournalLineContribution, ResolvedJournalContribution
from src.ledger.base.decision_anchor import DecisionAnchor, DecisionAnchorError, journal_command_target
from src.ledger.base.opening import OpeningPosition
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
    AccountPostingProtocol,
    JournalEntryPostingProtocol,
    JournalLinePostingProtocol,
    ValidationError,
    validate_fx_rates,
    validate_journal_balance,
    validate_journal_posting_invariants,
)
from src.ledger.base.vocabulary import (
    DEFAULT_BASE_CURRENCY,
    AccountType,
    Direction,
    JournalEntryAuthorityState,
    JournalEntryStatus,
)

__all__ = [
    "DEFAULT_BASE_CURRENCY",
    "AccountPostingProtocol",
    "AccountType",
    "AccountingError",
    "DecisionAnchor",
    "DecisionAnchorError",
    "DegenerateEntryError",
    "Direction",
    "Entry",
    "JournalEntryAuthorityState",
    "JournalEntryPostingProtocol",
    "JournalEntryStatus",
    "JournalLineContribution",
    "JournalLinePostingProtocol",
    "LedgerError",
    "Leg",
    "OpeningPosition",
    "ProcessingAccount",
    "ProcessingCurrencyConflictError",
    "ResolvedJournalContribution",
    "TransferAccountCurrencyMismatchError",
    "TransferPair",
    "UnbalancedEntryError",
    "ValidationError",
    "detect_transfer_pattern",
    "journal_command_target",
    "validate_fx_rates",
    "validate_journal_balance",
    "validate_journal_posting_invariants",
]
