"""``ledger`` — the double-entry bookkeeping bounded context (a ``core`` package).

The conforming implementation of ``common/ledger`` (its ``contract.py`` + ``readme.md``
own the spec). Layers converge by folder (see ``common/meta/migration-standard.md``):

- ``base/``      — pure core: the ``Entry``/``Leg`` balance invariant, the typed
                   errors, the three pure posting validators, and the
                   ``JournalRepository`` *port*. No I/O.
- ``extension/`` — impure edges: ``post_entry`` (the posting domain service) and the
                   ``AsyncSession`` adapter (``create``/``post``/``void`` +
                   ``validate_line_account_ownership``) that satisfies the port.
- ``data/``      — the account-balance projection (read model / leaf sink): signed
                   balances + the accounting-equation check.

The published language below (``__all__``) must equal ``contract.interface``.

The surface is exposed **lazily** via ``__getattr__`` so a caller that only needs the
pure ``Entry``/``Leg`` types (e.g. tooling tests, or ``services.accounting`` building
an opening-balance entry) does not eagerly pull the ``extension`` ORM/``AsyncSession``
edge into its import graph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.ledger.base import (
        AccountingError,
        DegenerateEntryError,
        Entry,
        JournalRepository,
        LedgerError,
        Leg,
        ProcessingAccount,
        TransferPair,
        UnbalancedEntryError,
        ValidationError,
        detect_transfer_pattern,
        validate_fx_rates,
        validate_journal_balance,
        validate_journal_posting_invariants,
    )
    from src.ledger.data import (
        StatementCoverageRow,
        calculate_account_balance,
        calculate_account_balances,
        register_statement_coverage_reader,
        verify_accounting_equation,
    )
    from src.ledger.extension import (
        RevaluationError,
        SqlJournalRepository,
        calculate_unrealized_fx_gains,
        create_journal_entry,
        create_transfer_in_entry,
        create_transfer_out_entry,
        find_transfer_pairs,
        get_opening_balance_readiness,
        get_or_create_processing_account,
        get_processing_balance,
        get_unpaired_transfers,
        list_processing_transfer_legs,
        post_entry,
        post_journal_entry,
        register_fx_revaluation_provider,
        used_currencies,
        validate_line_account_ownership,
        void_journal_entry,
    )

# ORM models owned by this package (moved from src/models, #1675). Imported
# eagerly — unlike the lazy service surface below — so importing the published
# root registers the mapped classes on ``Base.metadata`` (the discovery side
# effect ``models/_registry.py`` relies on). ``JournalEntrySourceType`` is NOT
# re-exported here: the provenance/trust vocabulary is owned by ``audit``
# (``from src.audit import JournalEntrySourceType``).
from src.ledger.orm.account import Account, AccountType
from src.ledger.orm.journal import (
    ConfidenceTier,
    Direction,
    JournalAuditLog,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    derive_confidence_tier,
)

__all__ = [
    "Account",
    "AccountNotFoundError",
    "AccountType",
    "AccountingError",
    "ConfidenceTier",
    "DEFAULT_STALE_AFTER_DAYS",
    "DegenerateEntryError",
    "Direction",
    "Entry",
    "JournalAuditLog",
    "JournalEntry",
    "JournalEntryStatus",
    "JournalLine",
    "JournalRepository",
    "LedgerError",
    "Leg",
    "ProcessingAccount",
    "RevaluationError",
    "SqlJournalRepository",
    "StatementCoverageRow",
    "TransferPair",
    "UnbalancedEntryError",
    "ValidationError",
    "account_service",
    "calculate_account_balance",
    "calculate_account_balances",
    "calculate_unrealized_fx_gains",
    "create_journal_entry",
    "create_transfer_in_entry",
    "create_transfer_out_entry",
    "derive_confidence_tier",
    "detect_transfer_pattern",
    "find_transfer_pairs",
    "get_account_statement_coverage",
    "get_opening_balance_readiness",
    "get_or_create_processing_account",
    "get_processing_balance",
    "get_unpaired_transfers",
    "list_processing_transfer_legs",
    "post_entry",
    "post_journal_entry",
    "post_opening_balance_entry",
    "register_fx_revaluation_provider",
    "register_statement_coverage_reader",
    "used_currencies",
    "validate_fx_rates",
    "validate_journal_balance",
    "validate_journal_posting_invariants",
    "validate_line_account_ownership",
    "verify_accounting_equation",
    "void_journal_entry",
    "accounts_router",
    "journal_router",
    "transactions_router",
]

# Which submodule owns each published name (lazy import map).
_BASE_NAMES = {
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
}
_EXTENSION_NAMES = {
    "AccountNotFoundError",
    "RevaluationError",
    "account_service",
    "post_opening_balance_entry",
    "SqlJournalRepository",
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
    "register_fx_revaluation_provider",
    "used_currencies",
    "validate_line_account_ownership",
    "void_journal_entry",
}
_DATA_NAMES = {
    "DEFAULT_STALE_AFTER_DAYS",
    "StatementCoverageRow",
    "calculate_account_balance",
    "get_account_statement_coverage",
    "calculate_account_balances",
    "register_statement_coverage_reader",
    "verify_accounting_equation",
}


_ROUTER_NAMES = {
    "accounts_router",
    "journal_router",
    "transactions_router",
}


def __getattr__(name: str):
    if name in _BASE_NAMES:
        from src.ledger import base as _mod

        value = getattr(_mod, name)
    elif name in _EXTENSION_NAMES:
        from src.ledger import extension as _mod

        value = getattr(_mod, name)
    elif name in _DATA_NAMES:
        from src.ledger import data as _mod

        value = getattr(_mod, name)
    elif name in _ROUTER_NAMES:
        if name == "accounts_router":
            from src.ledger.extension.api.accounts import router as value
        elif name == "journal_router":
            from src.ledger.extension.api.journal import router as value
        elif name == "transactions_router":
            from src.ledger.extension.api.transactions import router as value
    else:
        raise AttributeError(f"module 'src.ledger' has no attribute {name!r}")
    # Cache so subsequent attribute access skips the re-import.
    globals()[name] = value
    return value
