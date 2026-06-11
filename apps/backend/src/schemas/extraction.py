"""Pydantic schemas for document extraction API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.models.statement import (
    BankStatementStatus,
    BankStatementTransactionStatus,
    ConfidenceLevel,
)
from src.schemas.base import ListResponse

if TYPE_CHECKING:
    from src.models.layer1 import UploadedDocument
    from src.models.layer2 import AtomicTransaction
    from src.models.statement_summary import StatementSummary

# Re-export enums with schema-friendly names for API consumers
BankStatementStatusEnum = BankStatementStatus
BankStatementTransactionStatusEnum = BankStatementTransactionStatus
ConfidenceLevelEnum = ConfidenceLevel


# --- Request Schemas ---


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


# Backwards-compatible alias: keep the name used for statement retries
# while sharing the same underlying schema as RetryParsingRequest.
RetryStatementRequest = RetryParsingRequest


class TransactionUpdateRequest(BaseModel):
    """Request to manually correct a transaction."""

    txn_date: date | None = None
    description: str | None = None
    amount: Decimal | None = None
    direction: str | None = None
    reference: str | None = None
    currency: str | None = None
    balance_after: Decimal | None = None
    suggested_category: str | None = None
    category_confidence: Decimal | None = None


# --- Response Schemas ---


class AtomicTransactionResponse(BaseModel):
    """Single Layer-2 atomic transaction (DWD fact) exposed to the review API.

    Mapped from ``AtomicTransaction``; the ``statement_id`` is the owning
    ``StatementSummary`` id so existing API consumers keep a statement anchor.
    """

    id: UUID
    statement_id: UUID | None = None
    txn_date: date
    description: str
    amount: Decimal
    direction: str
    reference: str | None = None
    currency: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_atomic(cls, txn: AtomicTransaction, statement_id: UUID | None = None) -> AtomicTransactionResponse:
        return cls(
            id=txn.id,
            statement_id=statement_id,
            txn_date=txn.txn_date,
            description=txn.description,
            amount=txn.amount,
            direction=txn.direction.value if hasattr(txn.direction, "value") else txn.direction,
            reference=txn.reference,
            currency=txn.currency,
            created_at=txn.created_at,
            updated_at=txn.updated_at,
        )


# Backwards-compatible alias: the schema was renamed from
# ``BankStatementTransactionResponse`` as part of EPIC-011 Stage 3.
BankStatementTransactionResponse = AtomicTransactionResponse


class BankStatementResponse(BaseModel):
    """Parsed statement envelope with its atomic transactions.

    Composed from ``StatementSummary`` (the DWD conform), the linked
    ``UploadedDocument`` (for ``file_path`` / ``original_filename``), and the
    list of ``AtomicTransaction`` rows resolved via ``source_documents``. Use
    :func:`compose_statement_response` to build instances.
    """

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
    created_at: datetime
    updated_at: datetime
    transactions: list[AtomicTransactionResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


def compose_statement_response(
    summary: StatementSummary,
    uploaded_document: UploadedDocument | None,
    atomic_txns: list[AtomicTransaction],
) -> BankStatementResponse:
    """Compose a ``BankStatementResponse`` from the layered DWD records.

    ``file_path`` / ``original_filename`` come from the linked ODS
    ``UploadedDocument`` (empty strings when the document link is missing). The
    transactions list is built from ``atomic_txns`` (already resolved by the
    caller via ``UploadedDocument`` -> ``source_documents``).
    """
    return BankStatementResponse(
        id=summary.id,
        user_id=summary.user_id,
        account_id=summary.account_id,
        file_path=uploaded_document.file_path if uploaded_document else "",
        original_filename=uploaded_document.original_filename if uploaded_document else "",
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
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        transactions=[AtomicTransactionResponse.from_atomic(txn, summary.id) for txn in atomic_txns],
    )


BankStatementListResponse = ListResponse[BankStatementResponse]


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
