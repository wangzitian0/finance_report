"""Typed reconciliation domain failures and review actions."""

from __future__ import annotations

from enum import StrEnum

from src.platform.base.errors import ConflictError, DomainError, ResourceNotFoundError


class ReconciliationError(DomainError):
    """Base class for expected reconciliation failures."""


class MatchNotFoundError(ResourceNotFoundError, ReconciliationError):
    """The requested reconciliation match is not visible to the caller."""


class AmountMismatchError(ReconciliationError):
    """A match cannot be accepted because its ledger amounts disagree."""


class EntryCreationError(ReconciliationError):
    """A match cannot be accepted because its journal entry cannot be created."""


class ReviewedDispositionError(ReconciliationError):
    """A reviewed source-posting command fails policy or posting validation."""


class ConsistencyCheckNotFoundError(ResourceNotFoundError, ReconciliationError):
    """The requested consistency check is not visible to the caller."""


class InvalidCheckActionError(ReconciliationError):
    """A consistency-check resolution action is unsupported."""


class UnresolvedConsistencyChecksError(ConflictError, ReconciliationError):
    """Batch approval is blocked while unresolved consistency checks remain."""


class AdjustmentValidationError(ReconciliationError):
    """A reconciliation rounding adjustment fails threshold or FX preconditions."""


class CheckResolutionAction(StrEnum):
    """Supported consistency-check resolution actions."""

    APPROVE = "approve"
    REJECT = "reject"
    FLAG = "flag"
