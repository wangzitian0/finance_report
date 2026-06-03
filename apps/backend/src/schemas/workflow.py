"""Schemas for user-facing workflow events."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from src.models.workflow import (
    WorkflowEventFamily,
    WorkflowEventSeverity,
    WorkflowEventStatus,
    WorkflowReportImpact,
)


def _validate_internal_action_href(value: str) -> str:
    if not value.startswith("/") or value.startswith("//") or "://" in value:
        raise ValueError("action_href must be an internal relative path")
    return value


class WorkflowEventCreate(BaseModel):
    """Input contract for deterministic workflow event upserts."""

    family: WorkflowEventFamily
    severity: WorkflowEventSeverity
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1)
    source_type: str = Field(min_length=1, max_length=50)
    source_id: UUID
    action_href: str = Field(min_length=1, max_length=500)
    report_impact: WorkflowReportImpact
    dedupe_key: str = Field(min_length=1, max_length=255)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("action_href")
    @classmethod
    def validate_action_href(cls, value: str) -> str:
        return _validate_internal_action_href(value)


class WorkflowEventStatusUpdate(BaseModel):
    """Lifecycle update payload for user-visible workflow events."""

    status: WorkflowEventStatus


class WorkflowEventResponse(BaseModel):
    """User-facing workflow event response contract."""

    id: UUID
    user_id: UUID
    occurred_at: datetime
    family: WorkflowEventFamily
    severity: WorkflowEventSeverity
    status: WorkflowEventStatus
    title: str
    summary: str
    source_type: str
    source_id: UUID
    action_href: str
    report_impact: WorkflowReportImpact
    dedupe_key: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
