"""SQLAlchemy models package."""

from src.models.account import Account, AccountType
from src.models.journal import (
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.models.ping_state import PingState
from src.models.market_data import FxRate
from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.models.statement import (
    BankStatement,
    BankStatementStatus,
    BankStatementTransaction,
    BankStatementTransactionStatus,
    ConfidenceLevel,
)
from src.models.user import User

# Alias for SSOT compatibility (account_events table / statements table naming)
AccountEvent = BankStatementTransaction
AccountEventStatus = BankStatementTransactionStatus
BankTransactionStatus = BankStatementTransactionStatus
Statement = BankStatement

__all__ = [
    "Account",
    "AccountEvent",  # Alias for BankStatementTransaction
    "AccountEventStatus",  # Alias for BankStatementTransactionStatus
    "AccountType",
    "BankStatement",
    "BankStatementStatus",
    "BankStatementTransaction",
    "BankStatementTransactionStatus",
    "BankTransactionStatus",  # Alias for BankStatementTransactionStatus
    "ConfidenceLevel",
    "Direction",
    "FxRate",
    "JournalEntry",
    "JournalEntrySourceType",
    "JournalEntryStatus",
    "JournalLine",
    "PingState",
    "ReconciliationMatch",
    "ReconciliationStatus",
    "Statement",  # Alias for BankStatement
    "User",
]
