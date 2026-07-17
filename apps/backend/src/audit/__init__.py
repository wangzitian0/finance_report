"""``src.audit`` — the number-governor's published package surface.

Re-exports the Shared-Kernel value objects and the TraceRecord assurance
boundary declared by ``common/audit/contract.py``. Domain-specific errors and
wire helpers mostly stay under their submodules because names collide; only the
collision-free cross-package interface is published here (#1421, #1610).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Eager mapper registration for Base.metadata discovery.
from src.audit import orm as _orm  # noqa: F401
from src.audit.base.trace import (
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceDecisionPolicy,
    TraceDecisionPolicyRegistry,
    TraceLineage,
    TraceRecord,
    TraceRecordType,
    TraceRecordValidationError,
    TraceResult,
    TraceScope,
    TraceScopeKind,
    TraceTargetClass,
    VersionedTraceRef,
)
from src.audit.base.trace_repository import TraceRecordRepository
from src.audit.data import TraceConfidenceProjection
from src.audit.extension import (
    JsonlTraceRecordStore,
    PromotionTraceAdapter,
    PromotionTraceContext,
    PromotionTracePolicy,
    SqlTraceRecordRepository,
    TraceEmitter,
    TraceJUnitAdapter,
    TraceRecordCodec,
    TraceRecordPersistenceError,
)
from src.audit.money import (
    Currency,
    CurrencyBalance,
    CurrencyBalances,
    ExchangeRate,
    Money,
    MoneyTolerance,
)
from src.audit.money.adopt import balance_check
from src.audit.money.convert import convert
from src.audit.money.currency import normalize_currency_code
from src.audit.money.errors import InvalidCurrencyError, MoneyError
from src.audit.money.rounding import to_money
from src.audit.promotion import (
    RECONCILIATION_AUTO_ACCEPT_SCORE,
    RECONCILIATION_REVIEW_SCORE,
    STATEMENT_BALANCE_TOLERANCE,
    InvariantResult,
    PromotionDecision,
    PromotionVerdict,
    evaluate_promotion,
    tier_rank,
)
from src.audit.quantity import Quantity, Unit
from src.audit.ratio import Ratio
from src.audit.unit_price import UNIT_PRICE_QUANTUM, UnitPrice

if TYPE_CHECKING:
    from src.audit.source_type_priority import (
        STATEMENT_SOURCE_TYPES,
        JournalEntrySourceType,
        SourceTypeDowngradeError,
        is_user_data_source_type,
        normalize_source_type,
        promote_entries_source_type,
        promote_entry_source_type,
        source_type_rank,
        source_type_tiebreak_key,
        statement_source_values,
    )

__all__ = [
    "CurrencyBalance",
    "CurrencyBalances",
    "Currency",
    "InvalidCurrencyError",
    "MoneyError",
    "balance_check",
    "convert",
    "normalize_currency_code",
    "to_money",
    "ExchangeRate",
    "Money",
    "MoneyTolerance",
    "RECONCILIATION_AUTO_ACCEPT_SCORE",
    "RECONCILIATION_REVIEW_SCORE",
    "STATEMENT_BALANCE_TOLERANCE",
    "STATEMENT_SOURCE_TYPES",
    "JournalEntrySourceType",
    "SourceTypeDowngradeError",
    "InvariantResult",
    "PromotionDecision",
    "PromotionVerdict",
    "evaluate_promotion",
    "tier_rank",
    "JsonlTraceRecordStore",
    "PromotionTraceAdapter",
    "PromotionTraceContext",
    "PromotionTracePolicy",
    "TraceAuthorityProfile",
    "TraceCausality",
    "TraceConfidenceProjection",
    "TraceDecisionOutcome",
    "TraceDecisionPolicy",
    "TraceDecisionPolicyRegistry",
    "TraceRecord",
    "TraceRecordCodec",
    "TraceRecordPersistenceError",
    "TraceRecordRepository",
    "TraceRecordType",
    "TraceRecordValidationError",
    "TraceResult",
    "TraceScope",
    "TraceScopeKind",
    "TraceTargetClass",
    "TraceEmitter",
    "TraceJUnitAdapter",
    "TraceLineage",
    "SqlTraceRecordRepository",
    "VersionedTraceRef",
    "Quantity",
    "Ratio",
    "Unit",
    "UNIT_PRICE_QUANTUM",
    "UnitPrice",
    "is_user_data_source_type",
    "normalize_source_type",
    "promote_entries_source_type",
    "promote_entry_source_type",
    "source_type_rank",
    "source_type_tiebreak_key",
    "statement_source_values",
]

_SOURCE_TYPE_NAMES = {
    "STATEMENT_SOURCE_TYPES",
    "JournalEntrySourceType",
    "SourceTypeDowngradeError",
    "is_user_data_source_type",
    "normalize_source_type",
    "promote_entries_source_type",
    "promote_entry_source_type",
    "source_type_rank",
    "source_type_tiebreak_key",
    "statement_source_values",
}


def __getattr__(name: str):
    if name in _SOURCE_TYPE_NAMES:
        from src.audit import source_type_priority as _mod

        value = getattr(_mod, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'src.audit' has no attribute {name!r}")
