"""Pydantic schemas for reconciliation API."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.extraction import EconomicIntent
from src.schemas.base import ListResponse, default_list


class ReconciliationStatusEnum(str, Enum):
    AUTO_ACCEPTED = "auto_accepted"
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class BankTransactionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    statement_id: UUID | None = None
    txn_date: date
    description: str
    amount: Decimal
    direction: str
    reference: str | None
    currency: str
    confidence_tier: str = "LOW"


class JournalEntrySummary(BaseModel):
    id: UUID
    entry_date: date
    memo: str | None
    status: str
    total_amount: Decimal
    confidence_tier: str | None = None


class ReconciliationMatchResponse(BaseModel):
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
    entries: list[JournalEntrySummary] = default_list()


ReconciliationMatchListResponse = ListResponse[ReconciliationMatchResponse]


class ReconciliationRunRequest(BaseModel):
    statement_id: UUID | None = None
    limit: Annotated[int, Field(ge=1, le=10000)] | None = None


class ReconciliationRunResponse(BaseModel):
    matches_created: int
    auto_accepted: int
    pending_review: int
    unmatched: int


class BatchAcceptRequest(BaseModel):
    match_ids: list[str]


class ReviewedDispositionRequest(BaseModel):
    intent: EconomicIntent
    counter_account_id: UUID
    category: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    rationale: Annotated[str, Field(min_length=1, max_length=500)]

    @field_validator("category", "rationale")
    @classmethod
    def normalize_semantic_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not (normalized := value.strip()):
            raise ValueError("semantic text cannot be blank")
        return normalized


class ReconciliationStatsResponse(BaseModel):
    total_transactions: int
    matched_transactions: int
    unmatched_transactions: int
    pending_review: int
    auto_accepted: int
    match_rate: float
    score_distribution: dict[str, int]


UnmatchedTransactionsResponse = ListResponse[BankTransactionSummary]


class AnomalyResponse(BaseModel):
    anomaly_type: str
    severity: str
    message: str


class ReconciliationAdjustmentRequest(BaseModel):
    account_id: UUID
    bank_balance: Decimal
    book_balance: Decimal
    threshold: Decimal = Decimal("0.05")
    entry_date: date | None = None
    fx_rate: Decimal | None = None


class ReconciliationAdjustmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    bank_balance: Decimal
    book_balance: Decimal
    difference: Decimal
    is_gain: bool
    journal_entry_id: UUID | None = None
    entry: JournalEntrySummary | None = None
