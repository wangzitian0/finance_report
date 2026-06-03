"""User-facing workflow event read model."""

from datetime import UTC, datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum as SQLEnum, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin


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


class WorkflowEvent(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """User-facing workflow event projection for upload-to-report state."""

    __tablename__ = "workflow_events"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_workflow_events_user_dedupe_key"),
        CheckConstraint(
            "action_href LIKE '/%' AND action_href NOT LIKE '//%' AND action_href NOT LIKE '%://%'",
            name="ck_workflow_events_action_href_internal",
        ),
        Index("idx_workflow_events_user_status_occurred", "user_id", "status", "occurred_at"),
        Index("idx_workflow_events_user_severity_occurred", "user_id", "severity", "occurred_at"),
        Index("idx_workflow_events_user_family_occurred", "user_id", "family", "occurred_at"),
        Index("idx_workflow_events_user_source", "user_id", "source_type", "source_id"),
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    family: Mapped[WorkflowEventFamily] = mapped_column(
        SQLEnum(
            WorkflowEventFamily,
            name="workflow_event_family_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    severity: Mapped[WorkflowEventSeverity] = mapped_column(
        SQLEnum(
            WorkflowEventSeverity,
            name="workflow_event_severity_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    status: Mapped[WorkflowEventStatus] = mapped_column(
        SQLEnum(
            WorkflowEventStatus,
            name="workflow_event_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=WorkflowEventStatus.UNREAD,
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    action_href: Mapped[str] = mapped_column(String(500), nullable=False)
    report_impact: Mapped[WorkflowReportImpact] = mapped_column(
        SQLEnum(
            WorkflowReportImpact,
            name="workflow_report_impact_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=WorkflowReportImpact.NONE,
    )
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
