"""Pydantic schemas for AI chat endpoints."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatMessageRoleEnum(StrEnum):
    """Chat role enum for requests and responses."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatSessionStatusEnum(StrEnum):
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


class AdvisorSuggestion(BaseModel):
    """Source-cited, read-only advisor suggestion contract."""

    basis: str = Field(min_length=1, max_length=240)
    confidence_tier: str = Field(min_length=1, max_length=40)
    source_refs: list[str] = Field(default_factory=list)
    limitation: str = Field(min_length=1, max_length=500)
    next_action_href: str = Field(min_length=1, max_length=500)


class ChatCitation(BaseModel):
    """Application-owned citation metadata for one streamed chat answer."""

    label: str = Field(min_length=1, max_length=120)
    source_ref: str = Field(min_length=1, max_length=160)
    confidence_tier: str = Field(min_length=1, max_length=40)
    href: str = Field(min_length=1, max_length=500)


class ChatActionChip(BaseModel):
    """Safe next action rendered with one streamed chat answer."""

    kind: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=80)
    href: str = Field(min_length=1, max_length=500)
    count: int | None = Field(default=None, ge=0)


class ChatResponseMetadata(BaseModel):
    """Grounding metadata sent in the chat streaming response header."""

    grounded: bool = False
    citations: list[ChatCitation] = Field(default_factory=list)
    actions: list[ChatActionChip] = Field(default_factory=list)


class ChatSuggestionsResponse(BaseModel):
    """Suggested questions for the chat UI."""

    suggestions: list[str]
    structured_suggestions: list[AdvisorSuggestion] = Field(default_factory=list)
