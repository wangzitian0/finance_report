"""Pydantic schemas for document extraction API."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.models.statement import (
    BankStatementStatus,
    BankStatementTransactionStatus,
    ConfidenceLevel,
)
from src.schemas.base import ListResponse

# Re-export enums with schema-friendly names for API consumers
BankStatementStatusEnum = BankStatementStatus
BankStatementTransactionStatusEnum = BankStatementTransactionStatus
ConfidenceLevelEnum = ConfidenceLevel


# --- Request Schemas ---


class BankStatementUploadRequest(BaseModel):
    """Request to upload and parse a statement."""

    institution: str = Field(..., description="Bank/broker name (e.g., DBS, Wise)")
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


# --- Response Schemas ---


class BankStatementTransactionResponse(BaseModel):
    """Single transaction extracted from statement."""

    id: UUID
    statement_id: UUID
    txn_date: date
    description: str
    amount: Decimal
    direction: str
    reference: str | None
    status: BankStatementTransactionStatusEnum
    confidence: ConfidenceLevelEnum
    confidence_reason: str | None
    raw_text: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BankStatementResponse(BaseModel):
    """Parsed statement with transactions."""

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
    parsing_progress: int | None = 0
    balance_validated: bool | None
    validation_error: str | None
    created_at: datetime
    updated_at: datetime
    transactions: list[BankStatementTransactionResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


BankStatementListResponse = ListResponse[BankStatementResponse]


BankStatementTransactionListResponse = ListResponse[BankStatementTransactionResponse]


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
