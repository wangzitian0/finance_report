"""Pydantic schemas for authentication."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    """Schema for user registration."""

    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=128)]
    name: str | None = None


class LoginRequest(BaseModel):
    """Schema for user login."""

    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    """Schema for auth response - returns user info and JWT token."""

    id: UUID
    email: str
    name: str | None = None
    created_at: datetime
    access_token: str
    token_type: str = "bearer"

    model_config = ConfigDict(from_attributes=True)
