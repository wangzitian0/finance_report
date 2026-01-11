"""Pydantic schemas for users."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field


class UserBase(BaseModel):
    """Base user schema."""

    email: Annotated[str, Field(max_length=255)]


class UserCreate(UserBase):
    """Schema for creating a user."""

    password: Annotated[str, Field(min_length=8, max_length=128)]


class UserUpdate(BaseModel):
    """Schema for updating a user."""

    email: Annotated[str | None, Field(None, max_length=255)] = None


class UserResponse(UserBase):
    """Schema for user response."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    """Schema for user list response."""

    items: list[UserResponse]
    total: int
