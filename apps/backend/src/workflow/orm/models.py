"""User-facing workflow event read model."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.platform import TimestampMixin, UserOwnedMixin, UUIDMixin
from src.workflow.base.types import (
    WorkflowEventFamily,
    WorkflowEventSeverity,
    WorkflowEventStatus,
    WorkflowReportImpact,
    WorkflowSessionStatus,
)


class WorkflowSession(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """User-facing upload-to-report session header."""

    __tablename__ = "workflow_sessions"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_workflow_sessions_user_dedupe_key"),
        CheckConstraint(
            "report_href IS NULL OR (report_href LIKE '/%' AND report_href NOT LIKE '//%' AND report_href NOT LIKE '%://%')",
            name="ck_workflow_sessions_report_href_internal",
        ),
        Index("idx_workflow_sessions_user_status_last_event", "user_id", "status", "last_event_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[WorkflowSessionStatus] = mapped_column(
        SQLEnum(
            WorkflowSessionStatus,
            name="workflow_session_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=WorkflowSessionStatus.ACTIVE,
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="Upload-to-report session")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="Current upload-to-report workflow.")
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report_href: Mapped[str | None] = mapped_column(String(500), nullable=True)


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
        Index("idx_workflow_events_user_session_occurred", "user_id", "session_id", "occurred_at"),
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    session_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflow_sessions.id", ondelete="SET NULL"),
        nullable=True,
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
