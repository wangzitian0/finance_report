"""``ledger.extension`` — impure edges: anchored commands + private SQL persistence.

Depends on ``src.database``-backed ORM models and an ``AsyncSession``. This is
where the package reaches I/O and persistence. ``post_entry`` is the typed posting
verb; all new financial facts enter through the decision-anchored command boundary.
"""

from __future__ import annotations

from src.ledger.extension import account_service
from src.ledger.extension.account_service import AccountNotFoundError
from src.ledger.extension.accounting import (
    get_opening_balance_readiness,
    post_opening_balance_entry,
)
from src.ledger.extension.anchored_posting import (
    AnchoredJournalCommand,
    current_anchored_journal_entries,
    submit_anchored_journal_entry,
    submit_manual_journal_entry,
    validate_manual_journal_entry_for_post,
)
from src.ledger.extension.contribution import list_journal_contributions
from src.ledger.extension.currencies import used_currencies
from src.ledger.extension.fx_revaluation import (
    RevaluationError,
    calculate_unrealized_fx_gains,
    register_fx_revaluation_provider,
)
from src.ledger.extension.post import post_entry
from src.ledger.extension.processing import (
    create_transfer_in_entry,
    create_transfer_out_entry,
    find_transfer_pairs,
    get_or_create_processing_account,
    get_processing_balance,
    get_unpaired_transfers,
    list_processing_transfer_legs,
)
from src.ledger.extension.repository import (
    post_journal_entry,
    validate_line_account_ownership,
    void_journal_entry,
)

__all__ = [
    "AccountNotFoundError",
    "AnchoredJournalCommand",
    "current_anchored_journal_entries",
    "list_journal_contributions",
    "RevaluationError",
    "account_service",
    "calculate_unrealized_fx_gains",
    "create_transfer_in_entry",
    "create_transfer_out_entry",
    "find_transfer_pairs",
    "get_opening_balance_readiness",
    "get_or_create_processing_account",
    "get_processing_balance",
    "get_unpaired_transfers",
    "list_processing_transfer_legs",
    "post_entry",
    "submit_anchored_journal_entry",
    "submit_manual_journal_entry",
    "validate_manual_journal_entry_for_post",
    "post_journal_entry",
    "post_opening_balance_entry",
    "register_fx_revaluation_provider",
    "used_currencies",
    "validate_line_account_ownership",
    "void_journal_entry",
]
