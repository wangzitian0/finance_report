"""Pydantic schemas for document extraction API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.statement_enums import BankStatementStatus
from src.schemas.base import ListResponse

if TYPE_CHECKING:
    from src.models.layer1 import UploadedDocument
    from src.models.layer2 import AtomicTransaction
    from src.models.statement_summary import StatementSummary

# Re-export the statement lifecycle status enum with a schema-friendly name.
BankStatementStatusEnum = BankStatementStatus


class CurrencyBalance(BaseModel):
    """One currency's opening/closing balance within a statement (#1123 AC1).

    A statement may hold balances in several currencies (Wise / IBKR / Futu).
    Each currency is an independent closed loop: ``open + ΣIN − ΣOUT ≈ close`` is
    validated per currency and never summed across currencies. A single-currency
    statement maps to a one-element array; the scalar ``opening_balance`` /
    ``closing_balance`` columns stay populated for backward compatibility.

    FX leg pairing, internal-transfer net-worth, and FX P&L (#1123 AC2/AC3/AC4)
    are out of scope here and tracked as follow-up.
    """

    currency: str = Field(..., description="ISO currency code (normalized upper-case)")
    opening: Decimal = Field(..., description="Opening balance in this currency")
    closing: Decimal = Field(..., description="Closing balance in this currency")

    model_config = ConfigDict(from_attributes=True)

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, value: str) -> str:
        return value.strip().upper()


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
    ``UploadedDocument``. Before the document link is written by the ingestion
    pipeline (e.g. the upload 202 response), the upload handler stashes the same
    values as transient attributes on the summary, so fall back to those.
    The transactions list is built from ``atomic_txns`` (already resolved by the
    caller via ``UploadedDocument`` -> ``source_documents``).
    """
    file_path = uploaded_document.file_path if uploaded_document else getattr(summary, "file_path", None)
    original_filename = (
        uploaded_document.original_filename if uploaded_document else getattr(summary, "original_filename", None)
    )
    return BankStatementResponse(
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
