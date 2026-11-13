"""Pydantic schemas for Stage 1 and Stage 2 review API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.extraction import Stage1Status
from src.reconciliation import CheckStatus, CheckType
from src.schemas.base import default_list
from src.schemas.extraction import BankStatementResponse, BankStatementStatusEnum

Stage1StatusEnum = Stage1Status


class BalanceValidationResult(BaseModel):
    opening_balance: str | None = None
    closing_balance: str | None
    calculated_closing: str
    opening_delta: str
    closing_delta: str
    opening_match: bool
    closing_match: bool
    validated_at: str
    previous_closing_balance: str | None = None
    previous_period_end: str | None = None
    cross_period_delta: str | None = None
    cross_period_match: bool | None = None
    has_date_gap: bool | None = None


class ReviewedStatementEnvelopeRequest(BaseModel):
    source_result_digest: Annotated[str, Field(min_length=64, max_length=64)]
    account_id: UUID
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    period_start: date
    period_end: date
    opening_balance: Decimal
    closing_balance: Decimal
    rationale: Annotated[str, Field(min_length=1, max_length=2000)]


class ReviewedStatementEnvelopeResponse(BaseModel):
    id: UUID
    source_result_digest: str
    account_id: UUID
    currency: str
    period_start: date
    period_end: date
    opening_balance: Decimal
    closing_balance: Decimal
    rationale: str
    review_trace_record_id: UUID
    created_at: datetime


class StatementReviewResponse(BankStatementResponse):
    stage1_status: Stage1StatusEnum | None = None
    balance_validation_result: BalanceValidationResult | None = None
    stage1_reviewed_at: datetime | None = None
    manual_opening_balance: Decimal | None = None
    source_result_digest: str | None = None
    source_missing_facts: list[str] = default_list()
    source_envelope_reviewable: bool = False
    reviewed_envelope: ReviewedStatementEnvelopeResponse | None = None
    pdf_url: str | None = None
    model_config = ConfigDict(from_attributes=True)


class Stage1ApprovalRequest(BaseModel):
    account_id: UUID | None = None
    create_account_if_missing: bool = False
    auto_fill_default_categories: bool = False


class SetOpeningBalanceRequest(BaseModel):
    opening_balance: Annotated[Decimal, Field(ge=Decimal("0"))]


class StatementReviewListResponse(BaseModel):
    items: list[StatementReviewResponse]
    total: int


class BankStatementWithStage1Response(BankStatementResponse):
    stage1_status: Stage1StatusEnum | None = None
    balance_validation_result: dict | None = None
    stage1_reviewed_at: datetime | None = None
    manual_opening_balance: Decimal | None = None
    model_config = ConfigDict(from_attributes=True)


class Stage1ApprovalResponse(BaseModel):
    """What the approval changed. The page refetches the statement, so this holds no transaction rows."""

    id: UUID
    account_id: UUID | None
    status: BankStatementStatusEnum
    validation_error: str | None
    journal_entries_created: int = 0


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


class ResolveCheckRequest(BaseModel):
    action: str
    note: str | None = None


class ResolveCurrencyRequest(BaseModel):
    currency: str


class ResolveCurrencyResponse(BaseModel):
    transaction_id: UUID
    currency: str
    currency_unresolved: bool
    resolved_by: UUID | None = None
    resolved_at: datetime | None = None


class BatchApproveRequest(BaseModel):
    match_ids: list[UUID] = default_list()
    run_id: str | None = None


class BatchRejectRequest(BaseModel):
    match_ids: list[UUID] = default_list()


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


class BatchApproveResponse(BaseModel):
    approved_count: int
    journal_entries_reconciled: int


class BatchRejectResponse(BaseModel):
    rejected_count: int


class ReviewConflictCandidate(BaseModel):
    id: UUID
    txn_date: date
    description: str
    amount: Decimal
    direction: str


class ReviewConflictsResponse(BaseModel):
    duplicates: list[ReviewConflictCandidate] = default_list()
    transfer_pairs: list[ReviewConflictCandidate] = default_list()
    resolved: bool = False


class ResolveConflictsRequest(BaseModel):
    action: Literal["confirm_distinct", "link_transfer"] = "confirm_distinct"
    note: Annotated[str, Field(max_length=500)] | None = None


class ReviewConflictsResolveResponse(BaseModel):
    resolved: bool
    resolved_at: datetime | None = None
