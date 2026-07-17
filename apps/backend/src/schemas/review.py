"""Pydantic schemas for Stage 1 and Stage 2 review API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.extraction.orm.statement_enums import Stage1Status
from src.reconciliation.orm.consistency_check import CheckStatus, CheckType
from src.schemas.extraction import (
    AtomicTransactionResponse,
    BankStatementResponse,
    BankStatementStatusEnum,
)

Stage1StatusEnum = Stage1Status


class BalanceValidationResult(BaseModel):
    opening_balance: str
    # #1390: null when the statement has no declared closing balance (was the
    # literal string "None").
    closing_balance: str | None
    calculated_closing: str
    opening_delta: str
    closing_delta: str
    opening_match: bool
    closing_match: bool
    validated_at: str


class ReviewedStatementEnvelopeRequest(BaseModel):
    """Human-confirmed facts for one exact immutable extraction result."""

    source_result_digest: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="SHA-256 digest of the current immutable extraction result",
    )
    account_id: UUID = Field(description="User-owned asset account that holds the statement cash")
    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO-4217 currency confirmed for the statement envelope",
    )
    period_start: date = Field(description="Confirmed inclusive statement period start")
    period_end: date = Field(description="Confirmed inclusive statement period end")
    opening_balance: Decimal = Field(description="Confirmed opening balance in statement currency")
    closing_balance: Decimal = Field(description="Confirmed closing balance in statement currency")
    rationale: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Reviewer evidence for confirming facts absent from the source result",
    )


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


class StatementReviewResponse(BaseModel):
    id: UUID
    user_id: UUID
    account_id: UUID | None
    file_path: str
    original_filename: str
    institution: str
    account_last4: str | None
    currency: str | None
    period_start: date | None
    period_end: date | None
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    status: BankStatementStatusEnum
    confidence_score: int | None
    balance_validated: bool | None
    validation_error: str | None
    stage1_status: Stage1StatusEnum | None = None
    balance_validation_result: BalanceValidationResult | None = None
    stage1_reviewed_at: datetime | None = None
    manual_opening_balance: Decimal | None = None
    source_result_digest: str | None = None
    source_missing_facts: list[str] = Field(
        default_factory=list,
        description="Current source facts that require a reviewed-envelope confirmation",
    )
    source_envelope_reviewable: bool = Field(
        default=False,
        description="Whether the current source's missing facts can be confirmed by a cash statement envelope",
    )
    reviewed_envelope: ReviewedStatementEnvelopeResponse | None = None
    created_at: datetime
    updated_at: datetime
    transactions: list[AtomicTransactionResponse] = Field(
        default_factory=list,
        description="Transactions extracted for this statement review",
    )
    pdf_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TransactionEditRequest(BaseModel):
    txn_id: UUID
    amount: Decimal | None = None
    description: str | None = None
    txn_date: date | None = None
    direction: str | None = None
    reference: str | None = None


class EditAndApproveRequest(BaseModel):
    edits: list[TransactionEditRequest] = Field(
        default_factory=list,
        description="Reviewer transaction corrections to validate before approval",
    )


class Stage1ApprovalRequest(BaseModel):
    create_account_if_missing: bool = False


class SetOpeningBalanceRequest(BaseModel):
    opening_balance: Decimal = Field(
        ...,
        ge=Decimal("0"),
        description="Manual opening balance used for the statement chain",
    )


class StatementReviewListResponse(BaseModel):
    items: list[StatementReviewResponse]
    total: int


class BankStatementWithStage1Response(BankStatementResponse):
    stage1_status: Stage1StatusEnum | None = None
    balance_validation_result: dict | None = None
    stage1_reviewed_at: datetime | None = None
    manual_opening_balance: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)


class Stage1ApprovalResponse(BankStatementResponse):
    journal_entries_created: int = 0


# --- Stage 2 Review Schemas (moved from routers/statements.py) ---


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
    action: str = Field(..., description="approve, reject, or flag")
    note: str | None = None


class ResolveCurrencyRequest(BaseModel):
    """Reviewer-specified currency for a ``currency_unresolved`` transaction (AC12.40.3)."""

    currency: str = Field(..., description="ISO-4217 alphabetic currency code, e.g. 'USD'")


class ResolveCurrencyResponse(BaseModel):
    """Result of resolving a transaction's currency."""

    transaction_id: UUID
    currency: str
    currency_unresolved: bool
    resolved_by: UUID | None = None
    resolved_at: datetime | None = None


class BatchApproveRequest(BaseModel):
    match_ids: list[UUID] = Field(
        default_factory=list,
        description="Reconciliation match identifiers to approve",
    )
    run_id: str | None = None


class BatchRejectRequest(BaseModel):
    match_ids: list[UUID] = Field(
        default_factory=list,
        description="Reconciliation match identifiers to reject",
    )


class Stage2PendingMatch(BaseModel):
    """A reconciliation match awaiting Stage-2 review (#1001).

    Replaces the untyped ``dict`` previously nested inside
    ``Stage2ReviewQueueResponse.pending_matches`` so the row shape is declared in
    OpenAPI and consumable by the generated frontend client.
    """

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
    """Typed result of ``POST /statements/batch-approve-matches`` (#1001).

    Replaces ``response_model=dict``. Failure modes (e.g. unresolved consistency
    checks) now surface as proper HTTP error responses (409) carrying the shared
    ``ErrorResponse`` shape, instead of being smuggled into a 200 body as
    ``{"success": false}``.
    """

    approved_count: int
    journal_entries_created: int
    journal_entries_reconciled: int


class BatchRejectResponse(BaseModel):
    """Typed result of ``POST /statements/batch-reject-matches`` (#1001)."""

    rejected_count: int


class ReviewConflictCandidate(BaseModel):
    """Candidate transaction conflict returned to Stage 1 conflict UI."""

    id: UUID
    txn_date: date
    description: str
    amount: Decimal
    direction: str


class ReviewConflictsResponse(BaseModel):
    """Conflict candidates for a statement."""

    duplicates: list[ReviewConflictCandidate] = Field(
        default_factory=list,
        description="Transaction candidates that may be duplicate entries",
    )
    transfer_pairs: list[ReviewConflictCandidate] = Field(
        default_factory=list,
        description="Opposite-direction transaction candidates that may be transfers",
    )
    # #962: whether the reviewer has already resolved these candidates. Lets the UI
    # derive the approval-blocked state from the persisted marker instead of
    # ephemeral client state, so a refresh (or another tab/session) stays correct.
    resolved: bool = False


class ResolveConflictsRequest(BaseModel):
    """Stage-1 conflict resolution decision (#962).

    ``action`` records the reviewer's intent for audit: ``confirm_distinct`` (the
    flagged duplicate rows are genuinely distinct) or ``link_transfer`` (the rows
    are a real transfer pair). Both unblock approval; the distinction is logged.
    """

    action: Literal["confirm_distinct", "link_transfer"] = "confirm_distinct"
    note: Annotated[str, Field(max_length=500)] | None = None


class ReviewConflictsResolveResponse(BaseModel):
    """Acknowledgement that Stage-1 conflicts were resolved."""

    resolved: bool
    resolved_at: datetime | None = None
