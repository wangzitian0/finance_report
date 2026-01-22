"""Pydantic schemas for users."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from src.schemas.base import ListResponse


class UserBase(BaseModel):
    """Base user schema."""

    email: EmailStr


class UserCreate(UserBase):
    """Schema for creating a user."""

    password: Annotated[str, Field(min_length=8, max_length=128)]


class UserUpdate(BaseModel):
    """Schema for updating a user."""

    email: EmailStr | None = None


class UserResponse(UserBase):
    """Schema for user response."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def ensure_timezone_aware(cls, v: datetime) -> datetime:
        """Ensure datetime fields are timezone-aware."""
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v


UserListResponse = ListResponse[UserResponse]
