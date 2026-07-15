"""add workflow events read model"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021_add_workflow_events"
down_revision = "0020_add_market_data_sync_state"
branch_labels = None
depends_on = None


FAMILY_VALUES = (
    "source.uploaded",
    "source.parsing.started",
    "source.parsing.completed",
    "source.parsing.failed",
    "record.validation.passed",
    "record.validation.failed",
    "ledger.auto_posted",
    "review.required",
    "review.completed",
    "reconciliation.blocked",
    "report.processing",
    "report.ready",
    "report.blocked",
    "report.generated",
)
SEVERITY_VALUES = ("info", "success", "warning", "action_required", "blocked")
STATUS_VALUES = ("unread", "read", "archived")


def _create_enum_if_missing(name: str, values: tuple[str, ...]) -> None:
    quoted_values = ", ".join(f"'{value}'" for value in values)
    op.execute(
        f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({quoted_values}); EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _create_enum_if_missing("workflow_event_family_enum", FAMILY_VALUES)
    _create_enum_if_missing("workflow_event_severity_enum", SEVERITY_VALUES)
    _create_enum_if_missing("workflow_event_status_enum", STATUS_VALUES)

    if not inspector.has_table("workflow_events"):
        op.create_table(
            "workflow_events",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "family",
                postgresql.ENUM(*FAMILY_VALUES, name="workflow_event_family_enum", create_type=False),
                nullable=False,
            ),
            sa.Column(
                "severity",
                postgresql.ENUM(*SEVERITY_VALUES, name="workflow_event_severity_enum", create_type=False),
                nullable=False,
            ),
            sa.Column(
                "status",
                postgresql.ENUM(*STATUS_VALUES, name="workflow_event_status_enum", create_type=False),
                nullable=False,
            ),
            sa.Column("title", sa.String(length=160), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("source_type", sa.String(length=50), nullable=False),
            sa.Column("source_id", sa.UUID(), nullable=False),
            sa.Column("action_href", sa.String(length=500), nullable=False),
            sa.Column("report_impact", sa.String(length=50), nullable=False),
            sa.Column("dedupe_key", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "dedupe_key", name="uq_workflow_events_user_dedupe_key"),
        )

    op.execute("CREATE INDEX IF NOT EXISTS ix_workflow_events_user_id ON workflow_events (user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_events_user_status_occurred "
        "ON workflow_events (user_id, status, occurred_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_events_user_severity_occurred "
        "ON workflow_events (user_id, severity, occurred_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_events_user_family_occurred "
        "ON workflow_events (user_id, family, occurred_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_events_user_source "
        "ON workflow_events (user_id, source_type, source_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_workflow_events_user_source")
    op.execute("DROP INDEX IF EXISTS idx_workflow_events_user_family_occurred")
    op.execute("DROP INDEX IF EXISTS idx_workflow_events_user_severity_occurred")
    op.execute("DROP INDEX IF EXISTS idx_workflow_events_user_status_occurred")
    op.execute("DROP INDEX IF EXISTS ix_workflow_events_user_id")
    op.drop_table("workflow_events")
    op.execute("DROP TYPE IF EXISTS workflow_event_status_enum")
    op.execute("DROP TYPE IF EXISTS workflow_event_severity_enum")
    op.execute("DROP TYPE IF EXISTS workflow_event_family_enum")
