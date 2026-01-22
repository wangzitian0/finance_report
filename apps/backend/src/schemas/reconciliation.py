"""Pydantic schemas for reconciliation API."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.base import ListResponse
from src.schemas.extraction import BankStatementTransactionStatusEnum


class ReconciliationStatusEnum(str, Enum):
    """Reconciliation match status."""

    AUTO_ACCEPTED = "auto_accepted"
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class BankTransactionSummary(BaseModel):
    """Summary of a bank transaction for reconciliation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    statement_id: UUID
    txn_date: date
    description: str
    amount: Decimal
    direction: str
    reference: str | None
    status: BankStatementTransactionStatusEnum


class JournalEntrySummary(BaseModel):
    """Summary of a journal entry."""

    id: UUID
    entry_date: date
    memo: str | None
    status: str
    total_amount: Decimal


class ReconciliationMatchResponse(BaseModel):
    """Match response with transaction and entry details."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    bank_txn_id: UUID
    journal_entry_ids: list[str]
    match_score: int
    score_breakdown: dict[str, float]
    status: ReconciliationStatusEnum
    version: int
    superseded_by_id: UUID | None
    created_at: datetime
    updated_at: datetime
    transaction: BankTransactionSummary | None = None
    entries: list[JournalEntrySummary] = Field(default_factory=list)


ReconciliationMatchListResponse = ListResponse[ReconciliationMatchResponse]


class ReconciliationRunRequest(BaseModel):
    """Request body to run reconciliation."""

    statement_id: UUID | None = None
    limit: int | None = Field(default=None, ge=1, le=10000)


class ReconciliationRunResponse(BaseModel):
    """Response for reconciliation run."""

    matches_created: int
    auto_accepted: int
    pending_review: int
    unmatched: int


class BatchAcceptRequest(BaseModel):
    """Request body for batch accept."""

    match_ids: list[str]


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
