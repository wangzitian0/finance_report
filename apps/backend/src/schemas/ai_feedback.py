"""Schemas for AI suggestion feedback."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AiFeedbackRequest(BaseModel):
    suggestion_id: UUID
    action: Literal["accept", "reject", "edit_accept"]
    corrected_value: dict[str, Any] | None = None


class AiFeedbackResponse(BaseModel):
    id: UUID
    suggestion_id: UUID
    user_id: UUID
    action: str
    corrected_value: dict[str, Any] | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AiSuggestionResponse(BaseModel):
    suggestion_id: UUID
    transaction: str
    suggested_category_or_match: str
    ai_score: int = Field(..., ge=60, le=84)
    ai_reasoning: str


class AiSuggestionListResponse(BaseModel):
    items: list[AiSuggestionResponse]
    total: int
