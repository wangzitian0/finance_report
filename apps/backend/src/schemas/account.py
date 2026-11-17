"""Pydantic schemas for accounts."""

from datetime import date, datetime
from decimal import Decimal
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
