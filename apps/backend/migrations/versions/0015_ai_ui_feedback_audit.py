"""Add AI feedback, settings, and audit trail.

Revision ID: 0015_ai_ui_feedback_audit
Revises: 0014_add_correction_logs
Create Date: 2026-04-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015_ai_ui_feedback_audit"
down_revision = "bc9a8105e644"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "ai_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "ai_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("suggestion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("corrected_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_ai_feedback_suggestion_id", "ai_feedback", ["suggestion_id"])
    op.create_index("ix_ai_feedback_user_id", "ai_feedback", ["user_id"])

    op.create_table(
        "journal_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("journal_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_journal_audit_log_entry_id", "journal_audit_log", ["entry_id"])


def downgrade() -> None:
    op.drop_index("ix_journal_audit_log_entry_id", table_name="journal_audit_log")
    op.drop_table("journal_audit_log")
    op.drop_index("ix_ai_feedback_user_id", table_name="ai_feedback")
    op.drop_index("ix_ai_feedback_suggestion_id", table_name="ai_feedback")
    op.drop_table("ai_feedback")
    op.drop_column("users", "ai_settings")
