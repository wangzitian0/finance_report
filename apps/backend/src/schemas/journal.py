"""Pydantic schemas for journal entries."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

from src.audit import JournalEntrySourceType, normalize_source_type
from src.ledger import (
    MAX_JOURNAL_LINE_AMOUNT as _MAX_AMT,
    MAX_JOURNAL_LINE_FX_RATE as _MAX_FX,
    ConfidenceTier,
    Direction,
    JournalEntryAuthorityState,
    JournalEntryStatus,
    validate_journal_line_amount,
    validate_journal_line_fx_rate,
    validate_journal_line_tags,
)
from src.schemas.base import BaseResponse, CurrencyCode, ListResponse

JournalLineAmount = Annotated[
    Decimal, Field(gt=0, lt=_MAX_AMT, decimal_places=2), AfterValidator(validate_journal_line_amount)
]
JournalLineFxRate = Annotated[
    Decimal | None, Field(None, gt=0, lt=_MAX_FX, decimal_places=6), AfterValidator(validate_journal_line_fx_rate)
]
JournalLineTags = Annotated[dict | None, AfterValidator(validate_journal_line_tags)]
JournalSourceType = Annotated[JournalEntrySourceType, BeforeValidator(normalize_source_type)]
Text500 = Annotated[str, Field(min_length=1, max_length=500)]


class JournalLineBase(BaseModel):
    account_id: UUID
    direction: Direction
    amount: JournalLineAmount
    currency: CurrencyCode
    fx_rate: JournalLineFxRate = None
    event_type: Annotated[str, Field(max_length=100)] | None = None
    tags: JournalLineTags = None


class JournalLineCreate(JournalLineBase):
    currency: CurrencyCode | None = None  # type: ignore[assignment]


class JournalLineResponse(JournalLineBase, BaseResponse):
    id: UUID
    journal_entry_id: UUID
    created_at: datetime
    updated_at: datetime


class JournalEntryBase(BaseModel):
    entry_date: date
    memo: Text500
    source_type: JournalSourceType = JournalEntrySourceType.MANUAL
    source_id: UUID | None = None


class JournalEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_date: date
    memo: Text500
    rationale: Text500 = "Manual entry submitted by account owner."
    lines: Annotated[list[JournalLineCreate], Field(min_length=2)]


class JournalEntryResponse(JournalEntryBase, BaseResponse):
    id: UUID
    user_id: UUID
    status: JournalEntryStatus
    confidence_tier: ConfidenceTier | None = None
    decision_authority_state: JournalEntryAuthorityState
    decision_anchor_id: UUID | None = None
    void_reason: str | None = None
    void_reversal_entry_id: UUID | None = None
    lines: list[JournalLineResponse]
    created_at: datetime
    updated_at: datetime


JournalEntryListResponse = ListResponse[JournalEntryResponse]


class VoidJournalEntryRequest(BaseModel):
    reason: Text500
