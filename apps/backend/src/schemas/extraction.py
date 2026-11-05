"""Pydantic schemas for document extraction API."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.extraction import BankStatementStatus, TransactionCategory, brokerage_import_failure_reason
from src.schemas.base import CurrencyCode, ListResponse

if TYPE_CHECKING:
    from src.extraction import AtomicTransaction, ClassificationSuggestion, StatementSummary, UploadedDocument

# Re-export the statement lifecycle status enum with a schema-friendly name.
BankStatementStatusEnum = BankStatementStatus


class CurrencyBalance(BaseModel):
    """One currency's opening/closing balance within a statement (#1123 AC1)."""

    currency: CurrencyCode = Field(description="ISO currency code (normalized upper-case)")
    opening: Decimal = Field(..., description="Opening balance in this currency")
    closing: Decimal = Field(..., description="Closing balance in this currency")
    model_config = ConfigDict(from_attributes=True)


class BankStatementUploadRequest(BaseModel):
    """Request to upload and parse a statement."""

    institution: str | None = Field(None, description="Bank/broker name - auto-detected if omitted for PDF/image")
    file_type: str = Field(..., description="File type: pdf, csv, image")
    account_id: UUID | None = Field(None, description="Optional account link")


class StatementDecisionRequest(BaseModel):
    """Review decision payload for approve/reject."""

    notes: str | None = None


class RetryParsingRequest(BaseModel):
    """Request to retry parsing with an optional model override."""

    model: str | None = Field(None, description="Optional model override (e.g. gpt-4o)")


class AtomicTransactionResponse(BaseModel):
    """Single Layer-2 atomic transaction (DWD fact) exposed to the review API."""

    id: UUID
    statement_id: UUID | None = None
    source_row: int | None = Field(
        default=None, ge=1, description="1-based row ordinal in the source statement document."
    )
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
        proposed_category: TransactionCategory | None = None
        category: TransactionCategory | None = None
        confidence_score: int | None = None
        confidence_tier: Literal["HIGH", "MEDIUM", "LOW"] | None = None
        resolved_source_row = source_row if source_row is not None else getattr(txn, "source_row", None)
        if suggestion is not None:
            try:
                proposed_category = TransactionCategory(suggestion.category)
                category = proposed_category
            except ValueError:
                proposed_category = None
                category = None
            confidence_score = 100 if suggestion.corrected else suggestion.confidence
            if suggestion.corrected or suggestion.applied or confidence_score >= 85:
                confidence_tier = "HIGH"
            elif confidence_score >= 60:
                confidence_tier = "MEDIUM"
            else:
                confidence_tier = "LOW"
        return cls(
            id=txn.id,
            statement_id=statement_id,
            source_row=resolved_source_row,
            txn_date=txn.txn_date,
            description=txn.description,
            amount=txn.amount,
            direction=txn.direction.value if hasattr(txn.direction, "value") else txn.direction,
            reference=txn.reference,
            currency=txn.currency,
            balance_after=txn.balance_after,
            category=category,
            proposed_category=proposed_category,
            confidence_score=confidence_score,
            confidence_tier=confidence_tier,
            created_at=txn.created_at,
            updated_at=txn.updated_at,
        )


class BankStatementListItemResponse(BaseModel):
    """Statement envelope summary without embedded transactions (#2613)."""

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
    brokerage_import_failed: bool = Field(
        default=False,
        description="True when the last brokerage positions import of this parsed or approved statement "
        "failed (#2648). Only a successful import clears it.",
    )
    brokerage_import_failure_reason: str | None = Field(
        default=None,
        description="The reason of the failed import when brokerage_import_failed is true (#2648).",
    )
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BankStatementResponse(BankStatementListItemResponse):
    """Parsed statement envelope with its atomic transactions."""

    transactions: list[AtomicTransactionResponse] = Field(
        default_factory=list, description="Extracted atomic transactions associated with this statement"
    )


def compose_statement_list_item_response(
    summary: StatementSummary,
    uploaded_document: UploadedDocument | None,
) -> BankStatementListItemResponse:
    """Compose a ``BankStatementListItemResponse`` without transactions (#2613)."""
    file_path = uploaded_document.file_path if uploaded_document else getattr(summary, "file_path", None)
    original_filename = (
        uploaded_document.original_filename if uploaded_document else getattr(summary, "original_filename", None)
    )
    failure_reason = brokerage_import_failure_reason(summary)
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
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


def compose_statement_response(
    summary: StatementSummary,
    uploaded_document: UploadedDocument | None,
    atomic_txns: list[AtomicTransaction],
    suggestions: Mapping[UUID, ClassificationSuggestion] | None = None,
) -> BankStatementResponse:
    """Compose a ``BankStatementResponse`` from the layered DWD records."""
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
BankStatementTransactionListResponse = ListResponse[AtomicTransactionResponse]


class ParsedStatementPreview(BaseModel):
    """Preview of parsed data before saving (for validation)."""

    institution: str
    account_last4: str | None
    currency: str
    period_start: date
    period_end: date
    opening_balance: Decimal
    closing_balance: Decimal
    transactions_count: int
    confidence_score: int
    balance_validated: bool
    validation_error: str | None
