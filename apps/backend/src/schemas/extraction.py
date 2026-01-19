from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.models.extraction import BankStatementStatus


class BankStatementUploadRequest(BaseModel):
    institution: str = Field(..., description="Financial institution name (e.g. DBS, OCBC)")


class BankStatementResponse(BaseModel):
    id: UUID
    institution: str
    status: BankStatementStatus
    file_path: str
    original_filename: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BankStatementListResponse(BaseModel):
    statements: list[BankStatementResponse]


class BankStatementTransactionResponse(BaseModel):
    id: UUID
    statement_id: UUID
    date: date
    description: str
    amount: float
    currency: str
    transaction_type: Literal["DEBIT", "CREDIT"]
    raw_data: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class BankStatementTransactionListResponse(BaseModel):
    transactions: list[BankStatementTransactionResponse]


class StatementDecisionRequest(BaseModel):
    action: Literal["APPROVE", "REJECT"]


class RetryParsingRequest(BaseModel):
    """Request to retry parsing with an optional model override."""

    model: str | None = Field(None, description="Optional model override (e.g. gpt-4o)")


# Backwards-compatible alias: keep the name used for statement retries
# while sharing the same underlying schema as RetryParsingRequest.
RetryStatementRequest = RetryParsingRequest


class TransactionUpdateRequest(BaseModel):
    """Request to manually correct a transaction."""

    date: date | None = None
    description: str | None = None
    amount: float | None = None
    transaction_type: Literal["DEBIT", "CREDIT"] | None = None