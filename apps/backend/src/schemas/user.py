"""Compatibility exports plus the shared user-list wire envelope."""

from src.identity import (
    UserAiSettingsResponse,
    UserAiSettingsUpdate,
    UserBase,
    UserResponse,
    UserUpdate,
)
from src.schemas.base import ListResponse

UserListResponse = ListResponse[UserResponse]

__all__ = [
    "UserAiSettingsResponse",
    "UserAiSettingsUpdate",
    "UserBase",
    "UserListResponse",
    "UserResponse",
    "UserUpdate",
]
