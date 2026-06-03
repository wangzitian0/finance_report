"""Schemas for user-facing workflow events."""

from datetime import UTC, datetime
from enum import Enum
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


class WorkflowPrimaryState(str, Enum):
    """Compact upload-to-report state for primary UI surfaces."""

    EMPTY = "empty"
    PROCESSING = "processing"
    NEEDS_ACTION = "needs_action"
    BLOCKED = "blocked"
    READY = "ready"


class WorkflowNextActionType(str, Enum):
    """Primary next action exposed by the workflow status endpoint."""

    UPLOAD = "upload"
    WAIT = "wait"
    REVIEW_REQUIRED = "review_required"
    RESOLVE_BLOCKER = "resolve_blocker"
    OPEN_REPORT = "open_report"
    NONE = "none"


class WorkflowReportReadinessState(str, Enum):
    """Compact report readiness summary for upload/report surfaces."""

    NONE = "none"
    PROCESSING = "processing"
    READY = "ready"
    BLOCKED = "blocked"
    STALE = "stale"


class WorkflowNextActionResponse(BaseModel):
    """Next user action derived from current workflow events."""

    type: WorkflowNextActionType
    count: int = Field(ge=0)
    href: str

    @field_validator("href")
    @classmethod
    def validate_href(cls, value: str) -> str:
        return _validate_internal_action_href(value)


class WorkflowReportReadinessResponse(BaseModel):
    """Report readiness summary derived from workflow event impacts."""

    state: WorkflowReportReadinessState
    blocking_count: int = Field(ge=0)
    href: str

    @field_validator("href")
    @classmethod
    def validate_href(cls, value: str) -> str:
        return _validate_internal_action_href(value)


class WorkflowEventCountsResponse(BaseModel):
    """Header and inbox counters that do not require loading the full event list."""

    unread: int = Field(ge=0)
    action_required: int = Field(ge=0)
    blocked: int = Field(ge=0)


class WorkflowStatusResponse(BaseModel):
    """Compact user-scoped workflow status response."""

    primary_state: WorkflowPrimaryState
    next_action: WorkflowNextActionResponse
    report_readiness: WorkflowReportReadinessResponse
    event_counts: WorkflowEventCountsResponse


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


class WorkflowEventListResponse(BaseModel):
    """Bounded workflow event list response."""

    items: list[WorkflowEventResponse]
    total: int = Field(ge=0)
