"""Pydantic schemas for accounts."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from src.ledger import AccountType
from src.schemas.base import BaseResponse, CurrencyCode, ListResponse, MoneyAmount

MemoStr = Annotated[str, Field(min_length=1, max_length=500)]
NameStr = Annotated[str, Field(min_length=1, max_length=255)]
CodeStr = Annotated[str, Field(max_length=50)]
DescStr = Annotated[str, Field(max_length=500)]


class OpeningBalanceRequest(BaseModel):
    entry_date: date
    balances: dict[UUID, Annotated[Decimal, Field(gt=Decimal("0"), decimal_places=2)]]
    currency: CurrencyCode | None = None
    memo: MemoStr = "Opening balances"


class OpeningBalanceReadinessResponse(BaseModel):
    needs_opening_balance: bool
    has_activity: bool
    has_opening_entry: bool
    earliest_activity_date: date | None = None


class AccountBase(BaseModel):
    name: NameStr
    code: CodeStr | None = None
    type: AccountType
    currency: CurrencyCode = "SGD"
    parent_id: UUID | None = None
    description: DescStr | None = None


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    name: NameStr | None = None
    code: CodeStr | None = None
    description: DescStr | None = None
    parent_id: UUID | None = None
    is_active: bool | None = None


class AccountResponse(AccountBase, BaseResponse):
    id: UUID
    user_id: UUID
    is_active: bool
    is_system: bool
    balance: MoneyAmount | None = None
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
    currency: CurrencyCode
    period_start: date
    period_end: date
    statement_id: UUID | None = None
    previous_statement_id: UUID | None = None
    expected_opening_balance: MoneyAmount | None = None
    actual_opening_balance: MoneyAmount | None = None
    delta: MoneyAmount | None = None


class AccountCoverageResponse(BaseResponse):
    account_id: UUID
    account_name: str
    currency: CurrencyCode
    cadence: AccountCoverageCadence
    latest_source_date: date | None = None
    latest_confirmed_balance: MoneyAmount | None = None
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
    pending_total: MoneyAmount
    current_balance: MoneyAmount
    currency: CurrencyCode
    oldest_pending_date: date | None = None


class ProcessingPendingItem(BaseResponse):
    entry_id: UUID
    from_account: str
    to_account: str
    amount: MoneyAmount
    currency: CurrencyCode
    initiated_date: date
    days_outstanding: int
    description: str


ProcessingPendingListResponse = ListResponse[ProcessingPendingItem]
