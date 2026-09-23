"""Pure ledger domain vocabulary and enum definitions.

This module houses the core classification enums and constants of the double-entry
bookkeeping bounded context (Layer 3 domain). It has zero dependencies on ORM,
SQLAlchemy, database persistence, or runtime configuration.
"""

from __future__ import annotations

import enum

DEFAULT_BASE_CURRENCY = "SGD"


class AccountType(str, enum.Enum):
    """Account type classification.

    Follows the fundamental accounting equation:
    Assets = Liabilities + Equity + (Income - Expenses)
    """

    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class Direction(str, enum.Enum):
    """Debit or credit direction in double-entry bookkeeping."""

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class JournalEntryStatus(str, enum.Enum):
    """Status lifecycle of a journal entry."""

    DRAFT = "draft"
    POSTED = "posted"
    RECONCILED = "reconciled"
    VOID = "void"

    @classmethod
    def _missing_(cls, value: object) -> JournalEntryStatus | None:
        if isinstance(value, str):
            val_lower = value.lower()
            for member in cls:
                if member.value == val_lower:
                    return member
        return None


class JournalEntryAuthorityState(str, enum.Enum):
    """Whether a journal row has a decision that can be used as accounting authority."""

    ANCHORED = "anchored"
    LEGACY_UNPROVEN = "legacy_unproven"
