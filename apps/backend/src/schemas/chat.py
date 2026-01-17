"""Pydantic schemas for AI chat endpoints."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatMessageRoleEnum(str, Enum):
    """Chat role enum for requests and responses."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatSessionStatusEnum(str, Enum):
    """Session status enum."""

    ACTIVE = "active"
    DELETED = "deleted"


class ChatRequest(BaseModel):
    """Request payload for chat messages."""

    message: str = Field(min_length=1, max_length=4000)
    session_id: UUID | None = None
    model: str | None = Field(default=None, max_length=120)


class ChatMessageResponse(BaseModel):
    """Chat message response payload."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    role: ChatMessageRoleEnum
    content: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    model_name: str | None = None
    created_at: datetime


class ChatMessagePreview(BaseModel):
    """Short preview for listing sessions."""

    role: ChatMessageRoleEnum
    content: str
    created_at: datetime


class ChatSessionResponse(BaseModel):
    """Chat session response payload."""

    id: UUID
    title: str | None
    status: ChatSessionStatusEnum
    created_at: datetime
    updated_at: datetime
    last_active_at: datetime | None
    message_count: int = 0
    last_message: ChatMessagePreview | None = None
    messages: list[ChatMessageResponse] = Field(default_factory=list)


class ChatHistoryResponse(BaseModel):
    """Chat session list response payload."""

    sessions: list[ChatSessionResponse]


class ChatSuggestionsResponse(BaseModel):
    """Suggested questions for the chat UI."""

    suggestions: list[str]
