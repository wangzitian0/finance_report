"""Pydantic schemas for Stage 1 statement review/approval API."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.extraction.base.types.extraction import (
    AtomicTransactionResponse,
    BankStatementResponse,
)
from src.extraction.orm.statement_enums import BankStatementStatus, Stage1Status

BankStatementStatusEnum = BankStatementStatus
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
    created_at: datetime
    updated_at: datetime
    transactions: list[AtomicTransactionResponse] = Field(default_factory=list)
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
    edits: list[TransactionEditRequest] = Field(default_factory=list)


class Stage1ApprovalRequest(BaseModel):
    create_account_if_missing: bool = False


class SetOpeningBalanceRequest(BaseModel):
    opening_balance: Decimal = Field(..., ge=Decimal("0"))


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
