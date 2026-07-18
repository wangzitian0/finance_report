"""Pydantic schemas for reconciliation API."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.extraction.base.disposition import EconomicIntent
from src.schemas.base import ListResponse


class ReconciliationStatusEnum(str, Enum):
    """Reconciliation match status."""

    AUTO_ACCEPTED = "auto_accepted"
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class BankTransactionSummary(BaseModel):
    """Summary of a transaction for reconciliation.

    Mapped from Layer-2 ``AtomicTransaction`` (EPIC-011 Stage 3). ``statement_id``
    is retained as an optional field for backward compatibility with API
    consumers; atomic transactions do not carry a per-transaction status.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    statement_id: UUID | None = None
    txn_date: date
    description: str
    amount: Decimal
    direction: str
    reference: str | None
    confidence_tier: str = "LOW"


class JournalEntrySummary(BaseModel):
    """Summary of a journal entry."""

    id: UUID
    entry_date: date
    memo: str | None
    status: str
    total_amount: Decimal
    confidence_tier: str | None = None


class ReconciliationMatchResponse(BaseModel):
    """Match response with transaction and entry details."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    atomic_txn_id: UUID | None = None
    journal_entry_ids: list[str]
    match_score: int
    score_breakdown: dict[str, float | str]
    status: ReconciliationStatusEnum
    version: int
    superseded_by_id: UUID | None
    created_at: datetime
    updated_at: datetime
    transaction: BankTransactionSummary | None = None
    entries: list[JournalEntrySummary] = Field(
        default_factory=list,
        description="Journal entries proposed or linked for this reconciliation match.",
    )


ReconciliationMatchListResponse = ListResponse[ReconciliationMatchResponse]


class ReconciliationRunRequest(BaseModel):
    """Request body to run reconciliation."""

    statement_id: UUID | None = None
    limit: int | None = Field(
        default=None,
        ge=1,
        le=10000,
        description="Maximum number of source transactions to consider.",
    )


class ReconciliationRunResponse(BaseModel):
    """Response for reconciliation run."""

    matches_created: int
    auto_accepted: int
    pending_review: int
    unmatched: int


class BatchAcceptRequest(BaseModel):
    """Request body for batch accept."""

    match_ids: list[str]


class ReviewedDispositionRequest(BaseModel):
    """Explicit human-reviewed economic meaning for one unmatched source transaction."""

    intent: EconomicIntent
    counter_account_id: UUID
    category: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Required accounting category for P&L intents.",
    )
    rationale: str = Field(
        min_length=1,
        max_length=500,
        description="Reviewer rationale tied to the source evidence.",
    )

    @field_validator("category", "rationale")
    @classmethod
    def normalize_semantic_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("semantic text cannot be blank")
        return normalized


class ReconciliationStatsResponse(BaseModel):
    """Reconciliation statistics."""

    total_transactions: int
    matched_transactions: int
    unmatched_transactions: int
    pending_review: int
    auto_accepted: int
    match_rate: float
    score_distribution: dict[str, int]


UnmatchedTransactionsResponse = ListResponse[BankTransactionSummary]


class AnomalyResponse(BaseModel):
    """Response for anomalies."""

    anomaly_type: str
    severity: str
    message: str
