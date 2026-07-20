"""Pure value objects carried across extraction orchestration boundaries."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import TypedDict
from uuid import UUID


class PrefectParseParams(TypedDict):
    """JSON-safe wire representation of :class:`ParseJob`."""

    statement_id: str
    filename: str
    institution: str | None
    user_id: str
    account_id: str | None
    file_hash: str
    storage_key: str
    model: str | None
    request_id: str | None


class StatementIngestionStatus(StrEnum):
    """Terminal outcome of one application-level ingestion attempt."""

    COMPLETED = "completed"
    SOURCE_REJECTED = "source_rejected"
    STATEMENT_NOT_FOUND = "statement_not_found"


class StatementIngestionError(RuntimeError):
    """Base class for failures owned by the ingestion application boundary."""


class StatementIngestionConfigurationError(StatementIngestionError):
    """Required application composition is incomplete or invalid."""


class RetryableStatementIngestionError(StatementIngestionError):
    """Infrastructure/application failure that durable execution may retry."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RetireStatementCommand:
    """Idempotently retire one user-owned statement without purging facts."""

    statement_id: UUID
    user_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.statement_id, UUID):
            raise TypeError("statement_id must be a UUID")
        if not isinstance(self.user_id, UUID):
            raise TypeError("user_id must be a UUID")


@dataclass(frozen=True, slots=True, kw_only=True)
class StatementIngestionOutcome:
    """Typed result returned by every statement-ingestion transport."""

    statement_id: UUID
    status: StatementIngestionStatus
    transactions_count: int = 0
    auto_posted_count: int = 0


class StatementPostingStatus(StrEnum):
    """Terminal result of applying an already-decided statement posting plan."""

    POSTED = "posted"
    REVIEW_REQUIRED = "review_required"


@dataclass(frozen=True, slots=True, kw_only=True)
class StatementPostingOutcome:
    """Transport result for posting, not a second economic decision model.

    ``DispositionDecision`` remains the sole statement-to-ledger authority. This
    value object only preserves whether the fully evaluated plan was applied or
    deliberately returned to review, so callers cannot mistake zero created
    entries for a successful approval.
    """

    status: StatementPostingStatus
    created_count: int
    review_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.created_count < 0:
            raise ValueError("created_count cannot be negative")
        if self.status is StatementPostingStatus.POSTED and self.review_reasons:
            raise ValueError("posted outcome cannot carry review reasons")
        if self.status is StatementPostingStatus.REVIEW_REQUIRED and not self.review_reasons:
            raise ValueError("review-required outcome needs at least one reason")


@dataclass(frozen=True, slots=True, kw_only=True)
class ParseJob:
    """Immutable identity and routing context for one statement parse."""

    statement_id: UUID
    filename: str
    institution: str | None
    user_id: UUID
    account_id: UUID | None
    file_hash: str
    storage_key: str
    model: str | None
    request_id: str | None = None

    def to_prefect_params(self) -> PrefectParseParams:
        """Return the explicit JSON-safe contract accepted by the Prefect flow."""
        return {
            "statement_id": str(self.statement_id),
            "filename": self.filename,
            "institution": self.institution,
            "user_id": str(self.user_id),
            "account_id": str(self.account_id) if self.account_id is not None else None,
            "file_hash": self.file_hash,
            "storage_key": self.storage_key,
            "model": self.model,
            "request_id": self.request_id,
        }

    @classmethod
    def from_prefect_params(cls, params: Mapping[str, str | None]) -> ParseJob:
        """Rehydrate a job at the durable-worker boundary."""

        def required(key: str) -> str:
            value = params.get(key)
            if value is None:
                raise ValueError(f"Missing Prefect parse parameter: {key}")
            return value

        account_id = params.get("account_id")
        return cls(
            statement_id=UUID(required("statement_id")),
            filename=required("filename"),
            institution=params.get("institution"),
            user_id=UUID(required("user_id")),
            account_id=UUID(account_id) if account_id else None,
            file_hash=required("file_hash"),
            storage_key=required("storage_key"),
            model=params.get("model"),
            request_id=params.get("request_id"),
        )


@dataclass(frozen=True, slots=True)
class DocumentSource:
    """One normalized address and identity for a document being parsed."""

    path: Path
    content: bytes | None
    url: str | None
    content_hash: str
    filename: str

    @classmethod
    def resolve(
        cls,
        *,
        path: Path,
        content: bytes | None = None,
        url: str | None = None,
        content_hash: str | None = None,
        filename: str | None = None,
    ) -> DocumentSource:
        """Resolve all legacy source aliases exactly once at the call boundary."""
        resolved_hash = content_hash
        if resolved_hash is None or re.fullmatch(r"[0-9a-f]{64}", resolved_hash) is None:
            if content is None:
                raise ValueError("document source requires a lowercase sha256 content hash")
            resolved_hash = hashlib.sha256(content).hexdigest()
        return cls(
            path=path,
            content=content,
            url=url,
            content_hash=resolved_hash,
            filename=filename or path.name,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ExtractedTransactionRow:
    """Typed pre-persistence transaction row produced by document extraction."""

    user_id: UUID
    txn_date: date
    amount: Decimal
    direction: str
    description: str
    reference: str | None
    currency: str
    currency_unresolved: bool
    balance_after: Decimal | None
    occurrence_index: int
    dedup_hash: str
