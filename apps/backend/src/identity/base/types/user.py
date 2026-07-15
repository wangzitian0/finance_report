"""Identity-owned user CRUD and AI-settings wire vocabulary."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


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
    def ensure_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class UserAiSettingsUpdate(BaseModel):
    """AI feature flag settings that can be overridden per user."""

    enable_ai_reconciliation: bool | None = None
    enable_ai_classification: bool | None = None


class UserAiSettingsResponse(BaseModel):
    """Effective AI feature settings for the current user."""

    enable_ai_reconciliation: bool
    enable_ai_classification: bool


__all__ = [
    "UserAiSettingsResponse",
    "UserAiSettingsUpdate",
    "UserBase",
    "UserCreate",
    "UserResponse",
    "UserUpdate",
]
