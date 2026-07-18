"""``ledger`` — the double-entry bookkeeping bounded context (a ``core`` package).

The conforming implementation of ``common/ledger`` (its ``contract.py`` + ``readme.md``
own the spec). Layers converge by folder (see ``common/meta/migration-standard.md``):

- ``base/``      — pure core: the ``Entry``/``Leg`` balance invariant, typed
                   errors, posting validators, and command-target identity. No I/O.
- ``extension/`` — impure edges: the decision-anchored command boundary and its
                   private ``AsyncSession`` persistence implementation.
- ``data/``      — the account-balance projection (read model / leaf sink): signed
                   balances + the accounting-equation check.

The published language below (``__all__``) must equal ``contract.interface``.

The surface is exposed **lazily** via ``__getattr__`` so a caller that only needs the
pure ``Entry``/``Leg`` types (e.g. tooling tests, or ``services.accounting`` building
an opening-balance entry) does not eagerly pull the ``extension`` ORM/``AsyncSession``
edge into its import graph.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.ledger.base import (
        AccountingError,
        DecisionAnchor,
        DecisionAnchorError,
        DegenerateEntryError,
        Entry,
        LedgerError,
        Leg,
        ProcessingAccount,
        ProcessingCurrencyConflictError,
        TransferAccountCurrencyMismatchError,
        TransferPair,
        UnbalancedEntryError,
        ValidationError,
        detect_transfer_pattern,
        journal_command_target,
        validate_fx_rates,
        validate_journal_balance,
        validate_journal_posting_invariants,
    )
    from src.ledger.data import (
        StatementCoverageRow,
        calculate_account_balance,
        calculate_account_balances,
        calculate_account_balances_in_base_currency,
        register_statement_coverage_reader,
        verify_accounting_equation,
    )
    from src.ledger.extension import (
        AnchoredJournalCommand,
        RevaluationError,
        calculate_unrealized_fx_gains,
        create_transfer_in_entry,
        create_transfer_out_entry,
        current_anchored_journal_entries,
        find_transfer_pairs,
        get_opening_balance_readiness,
        get_or_create_processing_account,
        get_processing_balance,
        get_unpaired_transfers,
        list_processing_transfer_legs,
        post_entry,
        post_journal_entry,
        register_fx_revaluation_provider,
        submit_anchored_journal_entry,
        submit_manual_journal_entry,
        used_currencies,
        validate_line_account_ownership,
        validate_manual_journal_entry_for_post,
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
    JournalEntryAuthorityState,
    JournalEntryStatus,
    JournalLine,
    derive_confidence_tier,
    worst_confidence_tier,
)

__all__ = [
    "Account",
    "AccountNotFoundError",
    "AccountType",
    "AccountingError",
    "AnchoredJournalCommand",
    "current_anchored_journal_entries",
    "ConfidenceTier",
    "DEFAULT_STALE_AFTER_DAYS",
    "DegenerateEntryError",
    "DecisionAnchor",
    "DecisionAnchorError",
    "Direction",
    "Entry",
    "JournalAuditLog",
    "JournalEntry",
    "JournalEntryAuthorityState",
    "JournalEntryStatus",
    "JournalLine",
    "LedgerError",
    "Leg",
    "ProcessingAccount",
    "ProcessingCurrencyConflictError",
    "RevaluationError",
    "StatementCoverageRow",
    "TransferAccountCurrencyMismatchError",
    "TransferPair",
    "UnbalancedEntryError",
    "ValidationError",
    "account_service",
    "calculate_account_balance",
    "calculate_account_balances",
    "calculate_account_balances_in_base_currency",
    "calculate_unrealized_fx_gains",
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
    "journal_command_target",
    "list_processing_transfer_legs",
    "post_entry",
    "submit_anchored_journal_entry",
    "submit_manual_journal_entry",
    "validate_manual_journal_entry_for_post",
    "post_journal_entry",
    "post_opening_balance_entry",
    "register_fx_revaluation_provider",
    "register_statement_coverage_reader",
    "used_currencies",
    "worst_confidence_tier",
    "validate_fx_rates",
    "validate_journal_balance",
    "validate_journal_posting_invariants",
    "validate_line_account_ownership",
    "verify_accounting_equation",
    "void_journal_entry",
]

# Which submodule owns each published name (lazy import map).
_BASE_NAMES = {
    "AccountingError",
    "DecisionAnchor",
    "DecisionAnchorError",
    "DegenerateEntryError",
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
    "journal_command_target",
    "validate_fx_rates",
    "validate_journal_balance",
    "validate_journal_posting_invariants",
}
_EXTENSION_NAMES = {
    "AccountNotFoundError",
    "AnchoredJournalCommand",
    "current_anchored_journal_entries",
    "RevaluationError",
    "account_service",
    "post_opening_balance_entry",
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
    "calculate_account_balances_in_base_currency",
    "register_statement_coverage_reader",
    "verify_accounting_equation",
}


def __getattr__(name: str):
    if name in _BASE_NAMES:
        module_name = "src.ledger.base"
    elif name in _EXTENSION_NAMES:
        module_name = "src.ledger.extension"
    elif name in _DATA_NAMES:
        module_name = "src.ledger.data"
    else:
        raise AttributeError(f"module 'src.ledger' has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    # Cache so subsequent attribute access skips the re-import.
    globals()[name] = value
    return value
