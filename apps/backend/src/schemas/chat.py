"""Pydantic schemas for AI chat endpoints."""

from datetime import datetime
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.base import default_list


HrefStr = Annotated[str, Field(min_length=1, max_length=500)]
TierStr = Annotated[str, Field(min_length=1, max_length=40)]


class ChatMessageRoleEnum(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatSessionStatusEnum(str, Enum):
    ACTIVE = "active"
    DELETED = "deleted"


class ChatRequest(BaseModel):
    message: Annotated[str, Field(min_length=1, max_length=4000)]
    session_id: UUID | None = None
    model: Annotated[str, Field(max_length=120)] | None = None


class ChatMessageResponse(BaseModel):
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
    role: ChatMessageRoleEnum
    content: str
    created_at: datetime


class ChatSessionResponse(BaseModel):
    id: UUID
    title: str | None
    status: ChatSessionStatusEnum
    created_at: datetime
    updated_at: datetime
    last_active_at: datetime | None
    message_count: int = 0
    last_message: ChatMessagePreview | None = None
    messages: list[ChatMessageResponse] = default_list()


class ChatHistoryResponse(BaseModel):
    sessions: list[ChatSessionResponse]


class AdvisorSuggestion(BaseModel):
    basis: Annotated[str, Field(min_length=1, max_length=240)]
    confidence_tier: TierStr
    source_refs: list[str] = default_list()
    limitation: HrefStr
    next_action_href: HrefStr


class ChatCitation(BaseModel):
    label: Annotated[str, Field(min_length=1, max_length=120)]
    source_ref: Annotated[str, Field(min_length=1, max_length=160)]
    confidence_tier: TierStr
    href: HrefStr


class ChatActionChip(BaseModel):
    kind: Annotated[str, Field(min_length=1, max_length=80)]
    label: Annotated[str, Field(min_length=1, max_length=80)]
    href: HrefStr
    count: Annotated[int, Field(ge=0)] | None = None


class ChatResponseMetadata(BaseModel):
    grounded: bool = False
    citations: list[ChatCitation] = default_list()
    actions: list[ChatActionChip] = default_list()


class ChatSuggestionsResponse(BaseModel):
    suggestions: list[str]
    structured_suggestions: list[AdvisorSuggestion] = default_list()
