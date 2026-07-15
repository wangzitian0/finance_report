"""Compatibility exports plus the shared user-list wire envelope."""

from src.identity.base.types.user import (
    UserAiSettingsResponse,
    UserAiSettingsUpdate,
    UserBase,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from src.schemas.base import ListResponse

UserListResponse = ListResponse[UserResponse]

__all__ = [
    "UserAiSettingsResponse",
    "UserAiSettingsUpdate",
    "UserBase",
    "UserCreate",
    "UserListResponse",
    "UserResponse",
    "UserUpdate",
]
