"""Reconciliation base layer (pure value objects and repository port)."""

from src.reconciliation.base.config import (
    DEFAULT_CONFIG,
    MAX_COMBINATION_CANDIDATES,
    MatchCandidate,
    ReconciliationConfig,
    _candidate_is_better,
    _candidate_source_rank,
    entry_bank_side_amount,
    entry_total_amount,
    is_entry_balanced,
    load_reconciliation_config,
)
from src.reconciliation.base.errors import (
    AmountMismatchError,
    CheckResolutionAction,
    ConsistencyCheckNotFoundError,
    EntryCreationError,
    InvalidCheckActionError,
    MatchNotFoundError,
    ReconciliationError,
)
from src.reconciliation.base.prompts import (
    RECONCILIATION_SEMANTIC_PROMPT,
    build_reconciliation_prompt,
)
from src.reconciliation.base.repository import ReconciliationRepository

__all__ = [
    "AmountMismatchError",
    "CheckResolutionAction",
    "ConsistencyCheckNotFoundError",
    "DEFAULT_CONFIG",
    "EntryCreationError",
    "InvalidCheckActionError",
    "MAX_COMBINATION_CANDIDATES",
    "MatchNotFoundError",
    "MatchCandidate",
    "RECONCILIATION_SEMANTIC_PROMPT",
    "ReconciliationConfig",
    "ReconciliationError",
    "ReconciliationRepository",
    "_candidate_is_better",
    "_candidate_source_rank",
    "build_reconciliation_prompt",
    "entry_bank_side_amount",
    "entry_total_amount",
    "is_entry_balanced",
    "load_reconciliation_config",
]
