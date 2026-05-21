"""Pydantic schemas for accounts."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from src.models.account import AccountType
from src.schemas.base import BaseResponse, ListResponse


class AccountBase(BaseModel):
    """Base account schema."""

    name: Annotated[str, Field(min_length=1, max_length=255)]
    code: Annotated[str | None, Field(None, max_length=50)]
    type: AccountType
    currency: Annotated[str, Field(min_length=3, max_length=3)] = "SGD"
    parent_id: UUID | None = None
    description: Annotated[str | None, Field(None, max_length=500)] = None


class AccountCreate(AccountBase):
    """Schema for creating an account."""

    pass


class AccountUpdate(BaseModel):
    """Schema for updating an account."""

    name: Annotated[str | None, Field(None, min_length=1, max_length=255)] = None
    code: Annotated[str | None, Field(None, max_length=50)] = None
    description: Annotated[str | None, Field(None, max_length=500)] = None
    parent_id: UUID | None = None
    is_active: bool | None = None


class AccountResponse(AccountBase, BaseResponse):
    """Schema for account response."""

    id: UUID
    user_id: UUID
    is_active: bool
    is_system: bool
    balance: Annotated[Decimal, Field(decimal_places=2)] | None = None
    created_at: datetime
    updated_at: datetime


AccountListResponse = ListResponse[AccountResponse]


class AccountCoverageCadence(str, Enum):
    MONTHLY = "monthly"
    DAILY_SNAPSHOT = "daily_snapshot"


class AccountCoverageIssueType(str, Enum):
    GAP = "gap"
    OVERLAP = "overlap"
    DUPLICATE_PERIOD = "duplicate_period"
    OPENING_BALANCE_MISMATCH = "opening_balance_mismatch"


class AccountCoverageIssue(BaseResponse):
    type: AccountCoverageIssueType
    severity: str
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    period_start: date
    period_end: date
    statement_id: UUID | None = None
    previous_statement_id: UUID | None = None
    expected_opening_balance: Annotated[Decimal, Field(decimal_places=2)] | None = None
    actual_opening_balance: Annotated[Decimal, Field(decimal_places=2)] | None = None
    delta: Annotated[Decimal, Field(decimal_places=2)] | None = None


class AccountCoverageResponse(BaseResponse):
    account_id: UUID
    account_name: str
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    cadence: AccountCoverageCadence
    latest_source_date: date | None = None
    latest_confirmed_balance: Annotated[Decimal, Field(decimal_places=2)] | None = None
    stale_after_days: int
    is_stale: bool
    has_daily_snapshot_override: bool
    coverage_complete: bool
    issues: list[AccountCoverageIssue]


class AccountCoverageListResponse(BaseResponse):
    items: list[AccountCoverageResponse]
    total: int
    as_of: date


class ProcessingSummaryResponse(BaseResponse):
    pending_count: int
    pending_total: Annotated[Decimal, Field(decimal_places=2)]
    current_balance: Annotated[Decimal, Field(decimal_places=2)]
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    oldest_pending_date: date | None = None


class ProcessingPendingItem(BaseResponse):
    entry_id: UUID
    from_account: str
    to_account: str
    amount: Annotated[Decimal, Field(decimal_places=2)]
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    initiated_date: date
    days_outstanding: int
    description: str


ProcessingPendingListResponse = ListResponse[ProcessingPendingItem]
