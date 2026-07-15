"""Platform-owned workflow event and status payload vocabulary."""

from datetime import UTC, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class WorkflowEventFamily(str, Enum):
    """Product-level workflow event families."""

    SOURCE_UPLOADED = "source.uploaded"
    SOURCE_PARSING_STARTED = "source.parsing.started"
    SOURCE_PARSING_COMPLETED = "source.parsing.completed"
    SOURCE_PARSING_FAILED = "source.parsing.failed"
    RECORD_VALIDATION_PASSED = "record.validation.passed"
    RECORD_VALIDATION_FAILED = "record.validation.failed"
    LEDGER_AUTO_POSTED = "ledger.auto_posted"
    REVIEW_REQUIRED = "review.required"
    REVIEW_COMPLETED = "review.completed"
    RECONCILIATION_BLOCKED = "reconciliation.blocked"
    REPORT_PROCESSING = "report.processing"
    REPORT_READY = "report.ready"
    REPORT_BLOCKED = "report.blocked"
    REPORT_GENERATED = "report.generated"


class WorkflowEventSeverity(str, Enum):
    """User-facing actionability level."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ACTION_REQUIRED = "action_required"
    BLOCKED = "blocked"


class WorkflowEventStatus(str, Enum):
    """User-visible event lifecycle."""

    UNREAD = "unread"
    READ = "read"
    ARCHIVED = "archived"


class WorkflowReportImpact(str, Enum):
    """Impact of the event on report readiness."""

    NONE = "none"
    PROCESSING = "processing"
    READY = "ready"
    BLOCKED = "blocked"
    STALE = "stale"


class WorkflowSessionStatus(str, Enum):
    """Upload-to-report workflow session lifecycle."""

    ACTIVE = "active"
    GENERATED = "generated"
    ARCHIVED = "archived"


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
    label: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=240)

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


class WorkflowSessionSummaryResponse(BaseModel):
    """Workflow session header plus compact current state."""

    id: UUID
    status: WorkflowSessionStatus
    title: str
    summary: str
    started_at: datetime
    last_event_at: datetime | None = None
    source_count: int = Field(ge=0)
    report_href: str | None = None
    primary_state: WorkflowPrimaryState
    report_readiness: WorkflowReportReadinessResponse
    event_counts: WorkflowEventCountsResponse

    @field_validator("report_href")
    @classmethod
    def validate_report_href(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_internal_action_href(value)


class WorkflowStatusResponse(BaseModel):
    """Compact user-scoped workflow status response."""

    primary_state: WorkflowPrimaryState
    next_action: WorkflowNextActionResponse
    report_readiness: WorkflowReportReadinessResponse
    event_counts: WorkflowEventCountsResponse
    active_session: WorkflowSessionSummaryResponse | None = None


class WorkflowEventResponse(BaseModel):
    """User-facing workflow event response contract."""

    id: UUID
    user_id: UUID
    session_id: UUID | None = None
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
    sessions: list[WorkflowSessionSummaryResponse] = Field(default_factory=list)


__all__ = [
    "WorkflowEventCountsResponse",
    "WorkflowEventCreate",
    "WorkflowEventFamily",
    "WorkflowEventListResponse",
    "WorkflowEventResponse",
    "WorkflowEventSeverity",
    "WorkflowEventStatus",
    "WorkflowEventStatusUpdate",
    "WorkflowNextActionResponse",
    "WorkflowNextActionType",
    "WorkflowPrimaryState",
    "WorkflowReportImpact",
    "WorkflowReportReadinessResponse",
    "WorkflowReportReadinessState",
    "WorkflowSessionStatus",
    "WorkflowSessionSummaryResponse",
    "WorkflowStatusResponse",
]
