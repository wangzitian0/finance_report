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
        calculate_account_balance,
        calculate_account_balances,
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
        validate_line_account_ownership,
        void_journal_entry,
    )

__all__ = [
    "AccountingError",
    "DegenerateEntryError",
    "Entry",
    "JournalRepository",
    "LedgerError",
    "Leg",
    "ProcessingAccount",
    "RevaluationError",
    "SqlJournalRepository",
    "TransferPair",
    "UnbalancedEntryError",
    "ValidationError",
    "calculate_account_balance",
    "calculate_account_balances",
    "calculate_unrealized_fx_gains",
    "create_journal_entry",
    "create_transfer_in_entry",
    "create_transfer_out_entry",
    "detect_transfer_pattern",
    "find_transfer_pairs",
    "get_opening_balance_readiness",
    "get_or_create_processing_account",
    "get_processing_balance",
    "get_unpaired_transfers",
    "list_processing_transfer_legs",
    "post_entry",
    "post_journal_entry",
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
    "RevaluationError",
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
    "validate_line_account_ownership",
    "void_journal_entry",
}
_DATA_NAMES = {
    "calculate_account_balance",
    "calculate_account_balances",
    "verify_accounting_equation",
}


def __getattr__(name: str):
    if name in _BASE_NAMES:
        from src.ledger import base as _mod
    elif name in _EXTENSION_NAMES:
        from src.ledger import extension as _mod
    elif name in _DATA_NAMES:
        from src.ledger import data as _mod
    else:
        raise AttributeError(f"module 'src.ledger' has no attribute {name!r}")
    value = getattr(_mod, name)
    # Cache so subsequent attribute access skips the re-import.
    globals()[name] = value
    return value
