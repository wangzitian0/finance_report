"""SQLAlchemy models package."""

from src.models.account import Account, AccountType
from src.models.chat import ChatMessage, ChatMessageRole, ChatSession, ChatSessionStatus
from src.models.consistency_check import CheckStatus, CheckType, ConsistencyCheck
from src.models.correction import CorrectionLog
from src.models.journal import (
    Direction,
    JournalAuditLog,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.models.layer1 import DocumentStatus, DocumentType, UploadedDocument
from src.models.layer2 import AtomicPosition, AtomicTransaction, TransactionDirection
from src.models.layer3 import (
    ClassificationRule,
    ClassificationStatus,
    ManagedPosition,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
    PositionStatus,
    RuleType,
    TransactionClassification,
)
from src.models.layer4 import ReportSnapshot, ReportType
from src.models.market_data import FxRate, MarketDataSyncState, StockPrice
from src.models.ping_state import PingState
from src.models.portfolio import (
    DividendIncome,
    DividendType,
    InvestmentLot,
    InvestmentTransaction,
    InvestmentTransactionType,
    MarketDataOverride,
    PriceSource,
)
from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.models.statement import (
    BankStatement,
    BankStatementStatus,
    BankStatementTransaction,
    BankStatementTransactionStatus,
    ConfidenceLevel,
    Stage1Status,
)
from src.models.user import AiFeedback, User
from src.models.workflow import (
    WorkflowEvent,
    WorkflowEventFamily,
    WorkflowEventSeverity,
    WorkflowEventStatus,
    WorkflowReportImpact,
    WorkflowSession,
    WorkflowSessionStatus,
)

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
    "AiFeedback",
    "AtomicPosition",
    "AtomicTransaction",
    "BankStatement",
    "BankStatementStatus",
    "BankStatementTransaction",
    "BankStatementTransactionStatus",
    "BankTransactionStatus",  # Alias for BankStatementTransactionStatus
    "ChatMessage",
    "ChatMessageRole",
    "ChatSession",
    "ChatSessionStatus",
    "CheckStatus",
    "CheckType",
    "ConsistencyCheck",
    "ClassificationRule",
    "ClassificationStatus",
    "ConfidenceLevel",
    "CorrectionLog",
    "Direction",
    "DocumentStatus",
    "DocumentType",
    "FxRate",
    "JournalEntry",
    "JournalAuditLog",
    "JournalEntrySourceType",
    "JournalEntryStatus",
    "JournalLine",
    "DividendIncome",
    "DividendType",
    "InvestmentLot",
    "InvestmentTransaction",
    "InvestmentTransactionType",
    "PingState",
    "PositionStatus",
    "ManagedPosition",
    "MarketDataOverride",
    "MarketDataSyncState",
    "ManualValuationComponentType",
    "ManualValuationLiquidityClass",
    "ManualValuationSnapshot",
    "ReconciliationMatch",
    "ReconciliationStatus",
    "ReportSnapshot",
    "ReportType",
    "RuleType",
    "Statement",  # Alias for BankStatement
    "Stage1Status",
    "StockPrice",
    "PriceSource",
    "TransactionClassification",
    "TransactionDirection",
    "UploadedDocument",
    "User",
    "WorkflowEvent",
    "WorkflowEventFamily",
    "WorkflowEventSeverity",
    "WorkflowEventStatus",
    "WorkflowReportImpact",
    "WorkflowSession",
    "WorkflowSessionStatus",
]
