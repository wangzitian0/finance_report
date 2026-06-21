"""Typed errors for the ledger domain types."""

from __future__ import annotations


class LedgerError(Exception):
    """Base class for every ledger-domain error."""


class UnbalancedEntryError(LedgerError, ValueError):
    """An entry's debits and credits do not net to zero per currency.

    This is the system's central invariant: a double-entry posting must balance.
    ``Entry`` raises this at construction so an unbalanced entry is unrepresentable
    rather than caught later by a runtime check.
    """


class DegenerateEntryError(LedgerError, ValueError):
    """An entry was constructed with fewer than two legs.

    A double-entry posting needs at least one debit and one credit; an empty or
    single-leg entry is degenerate (and could never balance), so it is rejected
    with a clear error rather than a confusing "unbalanced" one.
    """
