"""Pydantic schemas for document extraction API."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class BankStatementStatusEnum(str, Enum):
    """Statement processing status."""

    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    APPROVED = "approved"
    REJECTED = "rejected"


class BankStatementTransactionStatusEnum(str, Enum):
    """Reconciliation status for a transaction."""

    PENDING = "pending"
    MATCHED = "matched"
    UNMATCHED = "unmatched"


class ConfidenceLevelEnum(str, Enum):
    """Confidence level for parsed data."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


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

    model: str | None = None


class RetryStatementRequest(BaseModel):
    """Request payload for retrying statement parsing."""

    model: str | None = Field(None, description="Optional model override (e.g. gpt-4o)")


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

    model_config = {"from_attributes": True}


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
    balance_validated: bool | None
    validation_error: str | None
    created_at: datetime
    updated_at: datetime
    transactions: list[BankStatementTransactionResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class BankStatementListResponse(BaseModel):
    """List of statements for review queue."""

    items: list[BankStatementResponse]
    total: int


class BankStatementTransactionListResponse(BaseModel):
    """List of statement transactions."""

    items: list[BankStatementTransactionResponse]
    total: int


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
