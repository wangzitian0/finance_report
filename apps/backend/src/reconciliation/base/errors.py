"""Typed reconciliation domain failures and review actions."""

from __future__ import annotations

from enum import StrEnum


class ReconciliationError(Exception):
    """Base class for expected reconciliation failures."""


class MatchNotFoundError(ReconciliationError):
    """The requested reconciliation match is not visible to the caller."""


class AmountMismatchError(ReconciliationError):
    """A match cannot be accepted because its ledger amounts disagree."""


class ConsistencyCheckNotFoundError(ReconciliationError):
    """The requested consistency check is not visible to the caller."""


class InvalidCheckActionError(ReconciliationError):
    """A consistency-check resolution action is unsupported."""


class CheckResolutionAction(StrEnum):
    """Supported consistency-check resolution actions."""

    APPROVE = "approve"
    REJECT = "reject"
    FLAG = "flag"
