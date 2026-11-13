"""Pydantic schemas for document extraction API."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.extraction import (
    BankStatementStatus,
    RunActorKind,
    RunHints,
    RunKind,
    RunState,
    RunTrigger,
    TransactionCategory,
    brokerage_import_failure_reason,
)
from src.schemas.base import CurrencyCode, ListResponse, default_list

if TYPE_CHECKING:
    from src.extraction import AtomicTransaction, ClassificationSuggestion, StatementSummary, UploadedDocument

BankStatementStatusEnum = BankStatementStatus


class CurrencyBalance(BaseModel):
    currency: CurrencyCode
    opening: Decimal
    closing: Decimal
    model_config = ConfigDict(from_attributes=True)


class BankStatementUploadRequest(BaseModel):
    institution: str | None = None
    file_type: str
    account_id: UUID | None = None


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
    """Run the extraction of a statement again, with optional hints (#2994).

    The actor of the run comes from the authenticated principal. The body cannot set it.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["extract"] = "extract"
    hints: RunHints = Field(
        default_factory=RunHints,
        description="Keywords and a note that guide the run. Empty hints leave the prompt unchanged.",
    )
    model: str | None = None


class StatementRunResponse(BaseModel):
    """One attempt to extract a statement: its inputs, its state and its error."""

    id: UUID
    seq: int
    kind: RunKind
    state: RunState
    actor_kind: RunActorKind
    trigger: RunTrigger
    parent_run_id: UUID | None = None
    hints: RunHints
    model: str | None = None
    prompt_template_version: str | None = None
    prompt_digest: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


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
    brokerage_import_failed: bool = False
    brokerage_import_failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BankStatementResponse(BankStatementListItemResponse):
    transactions: list[AtomicTransactionResponse] = default_list()


def compose_statement_list_item_response(
    summary: StatementSummary,
    uploaded_document: UploadedDocument | None,
) -> BankStatementListItemResponse:
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
StatementRunListResponse = ListResponse[StatementRunResponse]
BankStatementTransactionListResponse = ListResponse[AtomicTransactionResponse]


class ParsedStatementPreview(BaseModel):
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
