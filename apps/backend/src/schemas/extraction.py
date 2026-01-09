"""Pydantic schemas for document extraction API."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class StatementStatusEnum(str, Enum):
    """Statement processing status."""

    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    APPROVED = "approved"
    REJECTED = "rejected"


class ConfidenceLevelEnum(str, Enum):
    """Confidence level for parsed data."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# --- Request Schemas ---


class StatementUploadRequest(BaseModel):
    """Request to upload and parse a statement."""

    institution: str = Field(..., description="Bank/broker name (e.g., DBS, Moomoo)")
    file_type: str = Field(..., description="File type: pdf, csv, image")


class ReviewDecision(BaseModel):
    """Human review decision for a statement or event."""

    approved: bool
    notes: str | None = None


class EventUpdateRequest(BaseModel):
    """Request to manually correct an event."""

    txn_date: date | None = None
    description: str | None = None
    amount: Decimal | None = None
    direction: str | None = None
    reference: str | None = None


# --- Response Schemas ---


class AccountEventResponse(BaseModel):
    """Single transaction extracted from statement."""

    id: str
    txn_date: date
    description: str
    amount: Decimal
    direction: str
    reference: str | None
    confidence: ConfidenceLevelEnum
    confidence_reason: str | None
    raw_text: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class StatementResponse(BaseModel):
    """Parsed statement with events."""

    id: str
    file_path: str
    original_filename: str
    institution: str
    account_last4: str | None
    currency: str
    period_start: date
    period_end: date
    opening_balance: Decimal
    closing_balance: Decimal
    status: StatementStatusEnum
    confidence_score: int
    balance_validated: bool
    validation_error: str | None
    created_at: datetime
    updated_at: datetime
    events: list[AccountEventResponse] = []

    class Config:
        from_attributes = True


class StatementListResponse(BaseModel):
    """List of statements for review queue."""

    items: list[StatementResponse]
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
    events_count: int
    confidence_score: int
    balance_validated: bool
    validation_error: str | None
