"""Pydantic schemas for reconciliation API."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.extraction import EconomicIntent
from src.reconciliation import CheckStatus, CheckType
from src.schemas.base import BaseResponse, CurrencyCode, ListResponse, MoneyAmount, default_list


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


class ReconciliationMatchBatchRequest(BaseModel):
    action: Literal["accept", "reject"] = Field(
        default="accept",
        description="Batch action to apply to selected pending reconciliation matches.",
    )
    match_ids: list[UUID] = Field(
        default_factory=list,
        description="Identifiers of pending reconciliation matches to process.",
    )
    run_id: str | None = Field(
        default=None,
        description="Optional reconciliation run scope for conflict checks and match filtering.",
    )
    min_score: Annotated[
        int | None, Field(ge=0, le=100, description="Minimum match score required when accepting.")
    ] = None


class ReconciliationMatchBatchResponse(BaseModel):
    approved_count: int = Field(default=0, description="Count of matches accepted in the batch.")
    rejected_count: int = Field(default=0, description="Count of matches rejected in the batch.")
    journal_entries_reconciled: int = Field(default=0, description="Count of journal entries reconciled.")


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


class ReconciliationMatchDecisionRequest(BaseModel):
    action: Literal["accept", "reject"]


class ProcessingSummaryResponse(BaseResponse):
    pending_count: int
    pending_total: MoneyAmount
    current_balance: MoneyAmount
    currency: CurrencyCode
    oldest_pending_date: date | None = None


class ProcessingPendingItem(BaseResponse):
    entry_id: UUID
    from_account: str
    to_account: str
    amount: MoneyAmount
    currency: CurrencyCode
    initiated_date: date
    days_outstanding: int
    description: str


ProcessingPendingListResponse = ListResponse[ProcessingPendingItem]


class ConsistencyCheckResponse(BaseModel):
    id: UUID
    check_type: CheckType
    status: CheckStatus
    related_txn_ids: list[str]
    details: dict
    severity: str
    resolved_at: datetime | None = None
    resolution_note: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ConsistencyCheckListResponse(BaseModel):
    items: list[ConsistencyCheckResponse]
    total: int


class ConsistencyCheckRunRequest(BaseModel):
    statement_id: UUID


class ResolveCheckRequest(BaseModel):
    action: str
    note: str | None = None


class Stage2PendingMatch(BaseModel):
    id: UUID
    match_score: int
    status: str
    created_at: datetime | None = None
    description: str | None = None
    amount: Decimal | None = None
    txn_date: date | None = None
    confidence_tier: str


class Stage2ReviewQueueResponse(BaseModel):
    pending_matches: list[Stage2PendingMatch]
    consistency_checks: list[ConsistencyCheckResponse]
    has_unresolved_checks: bool
