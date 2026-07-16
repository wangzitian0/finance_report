"""Pydantic schemas for journal entries."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from src.audit import JournalEntrySourceType, normalize_source_type
from src.ledger import ConfidenceTier, Direction, JournalEntryStatus
from src.schemas.base import BaseResponse, CurrencyCode, ListResponse


class JournalLineBase(BaseModel):
    """Base journal line schema."""

    account_id: UUID
    direction: Direction
    amount: Annotated[Decimal, Field(gt=0, decimal_places=2)]
    currency: CurrencyCode
    fx_rate: Annotated[Decimal | None, Field(None, gt=0, decimal_places=6)] = None
    event_type: Annotated[str | None, Field(None, max_length=100)] = None
    tags: dict | None = None


class JournalLineCreate(JournalLineBase):
    """Schema for creating a journal line."""

    currency: CurrencyCode | None = None


class JournalLineResponse(JournalLineBase, BaseResponse):
    """Schema for journal line response."""

    id: UUID
    journal_entry_id: UUID
    created_at: datetime
    updated_at: datetime


class JournalEntryBase(BaseModel):
    """Base journal entry schema."""

    entry_date: date
    memo: Annotated[str, Field(min_length=1, max_length=500)]
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL
    source_id: UUID | None = None

    @field_validator("source_type", mode="before")
    @classmethod
    def normalize_source_type(cls, value: JournalEntrySourceType | str | None) -> JournalEntrySourceType:
        """Normalize deprecated legacy source types on API input."""
        return normalize_source_type(value)


class JournalEntryCreate(JournalEntryBase):
    """Schema for creating a journal entry."""

    lines: Annotated[list[JournalLineCreate], Field(min_length=2)]


class JournalEntryResponse(JournalEntryBase, BaseResponse):
    """Schema for journal entry response."""

    id: UUID
    user_id: UUID
    status: JournalEntryStatus
    confidence_tier: ConfidenceTier | None = None
    void_reason: str | None = None
    void_reversal_entry_id: UUID | None = None
    lines: list[JournalLineResponse]
    created_at: datetime
    updated_at: datetime


JournalEntryListResponse = ListResponse[JournalEntryResponse]


class VoidJournalEntryRequest(BaseModel):
    """Schema for voiding a journal entry."""

    reason: Annotated[str, Field(min_length=1, max_length=500)]
