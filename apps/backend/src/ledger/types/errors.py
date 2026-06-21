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


class EmptyEntryError(LedgerError, ValueError):
    """An entry was constructed with no legs."""
