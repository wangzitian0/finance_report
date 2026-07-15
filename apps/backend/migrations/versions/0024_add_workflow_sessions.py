"""add workflow sessions"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024_add_workflow_sessions"
down_revision = "0023_stmt_extract_metadata"
branch_labels = None
depends_on = None


SESSION_STATUS_VALUES = ("active", "generated", "archived")


def _create_enum_if_missing(name: str, values: tuple[str, ...]) -> None:
    quoted_values = ", ".join(f"'{value}'" for value in values)
    op.execute(
        f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({quoted_values}); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )


def upgrade() -> None:
    _create_enum_if_missing("workflow_session_status_enum", SESSION_STATUS_VALUES)
    op.create_table(
        "workflow_sessions",
        sa.Column(
            "status",
            postgresql.ENUM(*SESSION_STATUS_VALUES, name="workflow_session_status_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("report_href", sa.String(length=500), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "report_href IS NULL OR (report_href LIKE '/%' AND report_href NOT LIKE '//%' AND report_href NOT LIKE '%://%')",
            name="ck_workflow_sessions_report_href_internal",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_workflow_sessions_user_dedupe_key"),
    )
    op.create_index(
        "idx_workflow_sessions_user_status_last_event",
        "workflow_sessions",
        ["user_id", "status", "last_event_at"],
    )
    op.add_column("workflow_events", sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_workflow_events_session_id_workflow_sessions",
        "workflow_events",
        "workflow_sessions",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_workflow_events_user_session_occurred",
        "workflow_events",
        ["user_id", "session_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_workflow_events_user_session_occurred", table_name="workflow_events")
    op.drop_constraint("fk_workflow_events_session_id_workflow_sessions", "workflow_events", type_="foreignkey")
    op.drop_column("workflow_events", "session_id")
    op.drop_index("idx_workflow_sessions_user_status_last_event", table_name="workflow_sessions")
    op.drop_table("workflow_sessions")
    op.execute("DROP TYPE IF EXISTS workflow_session_status_enum")
