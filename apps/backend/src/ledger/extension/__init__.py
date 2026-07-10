"""``ledger.extension`` — the impure edges: the posting service + the SQL adapter.

Depends on ``src.database``-backed ORM models and an ``AsyncSession``. This is
where the package reaches I/O and persistence; the ``base`` layer stays pure behind
the :class:`~src.ledger.base.repository.JournalRepository` port this layer satisfies
(``SqlJournalRepository``). ``post_entry`` is the typed posting verb.
"""

from __future__ import annotations

from src.ledger.extension import account_service
from src.ledger.extension.account_service import AccountNotFoundError
from src.ledger.extension.accounting import (
    get_opening_balance_readiness,
    post_opening_balance_entry,
)
from src.ledger.extension.fx_revaluation import RevaluationError, calculate_unrealized_fx_gains
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
    SqlJournalRepository,
    create_journal_entry,
    post_journal_entry,
    validate_line_account_ownership,
    void_journal_entry,
)

__all__ = [
    "AccountNotFoundError",
    "RevaluationError",
    "SqlJournalRepository",
    "account_service",
    "calculate_unrealized_fx_gains",
    "create_journal_entry",
    "create_transfer_in_entry",
    "create_transfer_out_entry",
    "find_transfer_pairs",
    "get_opening_balance_readiness",
    "get_or_create_processing_account",
    "get_processing_balance",
    "get_unpaired_transfers",
    "list_processing_transfer_legs",
    "post_entry",
    "post_journal_entry",
    "post_opening_balance_entry",
    "validate_line_account_ownership",
    "void_journal_entry",
]
