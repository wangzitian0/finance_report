"""Pydantic schemas for accounts."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from src.models.account import AccountType


class AccountBase(BaseModel):
    """Base account schema."""

    name: Annotated[str, Field(min_length=1, max_length=255)]
    code: Annotated[str | None, Field(None, max_length=50)]
    type: AccountType
    currency: Annotated[str, Field(min_length=3, max_length=3)] = "SGD"
    description: Annotated[str | None, Field(None, max_length=500)] = None


class AccountCreate(AccountBase):
    """Schema for creating an account."""

    pass


class AccountUpdate(BaseModel):
    """Schema for updating an account."""

    name: Annotated[str | None, Field(None, min_length=1, max_length=255)] = None
    code: Annotated[str | None, Field(None, max_length=50)] = None
    description: Annotated[str | None, Field(None, max_length=500)] = None
    is_active: bool | None = None


class AccountResponse(AccountBase):
    """Schema for account response."""

    id: UUID
    user_id: UUID
    is_active: bool
    balance: Annotated[Decimal, Field(decimal_places=2)] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AccountListResponse(BaseModel):
    """Schema for account list response."""

    items: list[AccountResponse]
    total: int
