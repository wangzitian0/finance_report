"""Pydantic schemas for accounts."""

from datetime import datetime
from decimal import Decimal
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
