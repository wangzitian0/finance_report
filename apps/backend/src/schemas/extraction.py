"""Pydantic schemas for document extraction API."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from src.extraction import (
    BankStatementStatus,
    RunHints,
    Stage1Status,
    StatementIssueCode,
    StatementRunRecord,
    TransactionCategory,
    brokerage_import_failure_reason,
    classify_statement_issue_codes,
)
from src.schemas.base import BaseResponse, CurrencyCode, ListResponse, MoneyAmount, default_list

if TYPE_CHECKING:
    from src.extraction import AtomicTransaction, ClassificationSuggestion, StatementSummary, UploadedDocument


class StatementDecisionRequest(BaseModel):
    notes: str | None = Field(
        default=None,
        max_length=500,
        description="Why the reviewer rejects the statement. It becomes the hint note of the rerun.",
    )

    @field_validator("notes")
    @classmethod
    def _notes_fit_a_hint(cls, notes: str | None) -> str | None:
        """The notes become the hint note of the rerun, so they follow the hint rules."""
        RunHints(note=notes)
        return notes


class StatementRunRequest(BaseModel):
    """Run the extraction or the classification of a statement again, with optional hints (#2994).

    The actor of the run comes from the authenticated principal. The body cannot set it.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["extract", "classify"] = "extract"
    hints: RunHints = Field(
        default_factory=RunHints,
        description="Keywords and a note that guide the run. Empty hints leave the prompt unchanged.",
    )


class AtomicTransactionResponse(BaseModel):
    id: UUID
    statement_id: UUID | None = None
    source_row: Annotated[int, Field(ge=1)] | None = None
    txn_date: date
    description: str
    amount: Decimal
    direction: str
    reference: str | None = None
    currency: str | None = None
    balance_after: Decimal | None = None
    category: TransactionCategory | None = None
    proposed_category: TransactionCategory | None = None
    confidence_score: int | None = None
    confidence_tier: Literal["HIGH", "MEDIUM", "LOW"] | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_atomic(
        cls,
        txn: AtomicTransaction,
        statement_id: UUID | None = None,
        suggestion: ClassificationSuggestion | None = None,
        source_row: int | None = None,
    ) -> AtomicTransactionResponse:
        category: TransactionCategory | None = None
        confidence_score: int | None = None
        confidence_tier: Literal["HIGH", "MEDIUM", "LOW"] | None = None
        if suggestion is not None:
            try:
                category = TransactionCategory(suggestion.category)
            except ValueError:
                category = None
            confidence_score = 100 if suggestion.corrected else suggestion.confidence
            confidence_tier = (
                "HIGH"
                if suggestion.corrected or suggestion.applied or confidence_score >= 85
                else "MEDIUM"
                if confidence_score >= 60
                else "LOW"
            )
        return cls(
            id=txn.id,
            statement_id=statement_id,
            source_row=source_row if source_row is not None else getattr(txn, "source_row", None),
            txn_date=txn.txn_date,
            description=txn.description,
            amount=txn.amount,
            direction=txn.direction.value if hasattr(txn.direction, "value") else txn.direction,
            reference=txn.reference,
            currency=txn.currency,
            balance_after=txn.balance_after,
            category=category,
            proposed_category=category,
            confidence_score=confidence_score,
            confidence_tier=confidence_tier,
            created_at=txn.created_at,
            updated_at=txn.updated_at,
        )


class BankStatementListItemResponse(BaseModel):
    id: UUID
    user_id: UUID
    account_id: UUID | None
    file_path: str
    original_filename: str
    institution: str | None
    account_last4: str | None
    currency: str | None
    period_start: date | None
    period_end: date | None
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    status: BankStatementStatus
    confidence_score: int | None
    balance_validated: bool | None
    validation_error: str | None
    brokerage_import_failed: bool = False
    brokerage_import_failure_reason: str | None = None
    active_run_kind: str | None = Field(
        default=None,
        description="The kind of the requested or running run of the statement. Only the list routes fill it.",
    )
    issue_codes: list[StatementIssueCode] = Field(
        default_factory=list,
        description="Typed review, balance, and confirmation blockers derived from persisted statement state.",
    )
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BankStatementResponse(BankStatementListItemResponse):
    transactions: list[AtomicTransactionResponse] = default_list()


def _statement_issue_codes_from_summary(summary: StatementSummary, *, is_brokerage: bool) -> list[StatementIssueCode]:
    if summary.status not in (
        BankStatementStatus.PARSED,
        BankStatementStatus.REJECTED,
        BankStatementStatus.APPROVED,
    ):
        return []
    missing_facts: list[str] = []
    if not (summary.institution or "").strip():
        missing_facts.append("institution")
    if not (summary.currency or "").strip() and not summary.currency_balances:
        missing_facts.append("statement_currency")
    if summary.period_start is None or summary.period_end is None:
        missing_facts.append("period")
    if (
        not is_brokerage
        and summary.opening_balance is None
        and summary.closing_balance is None
        and not summary.currency_balances
    ):
        missing_facts.append("balances")
    return classify_statement_issue_codes(
        missing_facts=missing_facts,
        balance_validated=summary.balance_validated,
        has_account=summary.account_id is not None,
        validation_error=summary.validation_error,
    )


def compose_statement_list_item_response(
    summary: StatementSummary,
    uploaded_document: UploadedDocument | None,
) -> BankStatementListItemResponse:
    file_path = uploaded_document.file_path if uploaded_document else ""
    original_filename = uploaded_document.original_filename if uploaded_document else ""
    failure_reason = brokerage_import_failure_reason(summary)
    extraction_result_meta = (getattr(summary, "extraction_metadata", None) or {}).get("statement_extraction_result")
    is_brokerage = failure_reason is not None or (
        isinstance(extraction_result_meta, dict) and extraction_result_meta.get("is_brokerage") is True
    )
    return BankStatementListItemResponse(
        id=summary.id,
        user_id=summary.user_id,
        account_id=summary.account_id,
        file_path=file_path or "",
        original_filename=original_filename or "",
        institution=summary.institution,
        account_last4=summary.account_last4,
        currency=summary.currency,
        period_start=summary.period_start,
        period_end=summary.period_end,
        opening_balance=summary.opening_balance,
        closing_balance=summary.closing_balance,
        status=summary.status,
        confidence_score=summary.confidence_score,
        balance_validated=summary.balance_validated,
        validation_error=summary.validation_error,
        brokerage_import_failed=failure_reason is not None,
        brokerage_import_failure_reason=failure_reason,
        issue_codes=_statement_issue_codes_from_summary(summary, is_brokerage=is_brokerage),
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


def compose_statement_response(
    summary: StatementSummary,
    uploaded_document: UploadedDocument | None,
    atomic_txns: list[AtomicTransaction],
    suggestions: Mapping[UUID, ClassificationSuggestion] | None = None,
) -> BankStatementResponse:
    base_item = compose_statement_list_item_response(summary, uploaded_document)
    return BankStatementResponse(
        **base_item.model_dump(),
        transactions=[
            AtomicTransactionResponse.from_atomic(
                txn,
                summary.id,
                suggestion=suggestions.get(txn.id) if suggestions else None,
                source_row=getattr(txn, "source_row", idx + 1),
            )
            for idx, txn in enumerate(atomic_txns)
        ],
    )


BankStatementListResponse = ListResponse[BankStatementListItemResponse]
StatementRunListResponse = ListResponse[StatementRunRecord]


class AccountCoverageCadence(str, Enum):
    MONTHLY = "monthly"
    DAILY_SNAPSHOT = "daily_snapshot"


class AccountCoverageIssueType(str, Enum):
    GAP = "gap"
    OVERLAP = "overlap"
    DUPLICATE_PERIOD = "duplicate_period"
    OPENING_BALANCE_MISMATCH = "opening_balance_mismatch"


class AccountCoverageIssue(BaseResponse):
    type: AccountCoverageIssueType
    severity: str
    currency: CurrencyCode
    period_start: date
    period_end: date
    statement_id: UUID | None = None
    previous_statement_id: UUID | None = None
    expected_opening_balance: MoneyAmount | None = None
    actual_opening_balance: MoneyAmount | None = None
    delta: MoneyAmount | None = None


class AccountCoverageResponse(BaseResponse):
    account_id: UUID
    account_name: str
    currency: CurrencyCode
    cadence: AccountCoverageCadence
    latest_source_date: date | None = None
    latest_confirmed_balance: MoneyAmount | None = None
    stale_after_days: int
    is_stale: bool
    has_daily_snapshot_override: bool
    coverage_complete: bool
    issues: list[AccountCoverageIssue]


class AccountCoverageListResponse(BaseResponse):
    items: list[AccountCoverageResponse]
    total: int
    as_of: date


class AiFeedbackRequest(BaseModel):
    suggestion_id: UUID
    action: Literal["accept", "reject", "edit_accept"]
    corrected_value: dict[str, Any] | None = None


class AiFeedbackResponse(BaseModel):
    id: UUID
    suggestion_id: UUID
    user_id: UUID
    action: str
    corrected_value: dict[str, Any] | None = None
    created_at: datetime
    effect: str = Field(
        default="recorded",
        description=(
            "What the decision changed: accepted, rejected or corrected for a pending draft; "
            "recorded when the id is already superseded or applied, so only the feedback is stored."
        ),
    )

    model_config = ConfigDict(from_attributes=True)


class AiSuggestionResponse(BaseModel):
    suggestion_id: UUID
    transaction: str
    suggested_category_or_match: str
    ai_score: int = Field(..., ge=60, le=84, description="AI classification confidence score")
    ai_reasoning: str
    direction: Literal["IN", "OUT"] | None = None


class AiSuggestionListResponse(BaseModel):
    items: list[AiSuggestionResponse]
    total: int


class CorrectionRequest(BaseModel):
    """Request to record a user correction."""

    transaction_id: UUID
    corrected_category: str = Field(
        ..., min_length=1, max_length=100, description="User-corrected transaction category"
    )
    corrected_account_id: UUID | None = None


class CorrectionResponse(BaseModel):
    """Response after recording a correction."""

    id: UUID
    transaction_id: UUID
    original_category: str | None
    corrected_category: str


class CorrectionLoopReplayResponse(BaseModel):
    holdout_size: int
    grounded: int
    proportion_before: Decimal
    proportion_after: Decimal
    reduced: bool
    high_confidence_count: int = 0
    medium_confidence_count: int = 0
    low_confidence_count: int = 0
    low_confidence_proportion: Decimal = Decimal("0")


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
    institution: Annotated[
        str | None,
        # The value is trimmed first, so a blank value gives 422 and not an error in the command (#3167).
        StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
        Field(description="Required when source_missing_facts holds institution. Never replaces a source institution."),
    ] = None


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
    institution: str | None = None
    review_trace_record_id: UUID
    created_at: datetime


class StatementReviewResponse(BankStatementResponse):
    stage1_status: Stage1Status | None = None
    balance_validation_result: BalanceValidationResult | None = None
    stage1_reviewed_at: datetime | None = None
    manual_opening_balance: Decimal | None = None
    source_result_digest: str | None = None
    source_missing_facts: list[str] = default_list()
    source_envelope_reviewable: bool = False
    reviewed_envelope: ReviewedStatementEnvelopeResponse | None = None
    model_config = ConfigDict(from_attributes=True)


class Stage1ApprovalRequest(BaseModel):
    account_id: UUID | None = None
    create_account_if_missing: bool = False
    auto_fill_default_categories: bool = False
    expected_source_result_digest: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        description=(
            "The source_result_digest of the review that the user saw. "
            "Required when the statement has a current extraction result."
        ),
    )


class Stage1ApprovalResponse(BaseModel):
    """What the approval changed. The page refetches the statement, so this holds no transaction rows."""

    id: UUID
    account_id: UUID | None
    status: BankStatementStatus
    validation_error: str | None
    journal_entries_created: int = 0


class ReviewConflictCandidate(BaseModel):
    id: UUID
    txn_date: date
    description: str
    amount: Decimal
    direction: str


class OtherStatementMatchResponse(BaseModel):
    """An approved statement of another account whose rows equal the rows of this statement (#2917)."""

    statement_id: UUID
    account_name: str
    matched_rows: int
    total_rows: int


class ReviewConflictsResponse(BaseModel):
    duplicates: list[ReviewConflictCandidate] = default_list()
    transfer_pairs: list[ReviewConflictCandidate] = default_list()
    other_statement_matches: list[OtherStatementMatchResponse] = default_list()
    resolved: bool = False


class ResolveConflictsRequest(BaseModel):
    """The reviewer confirms that the listed candidates are different transactions. The call links no rows."""

    note: Annotated[str, Field(max_length=500)] | None = None


class ReviewConflictsResolveResponse(BaseModel):
    resolved: bool
    resolved_at: datetime | None = None
