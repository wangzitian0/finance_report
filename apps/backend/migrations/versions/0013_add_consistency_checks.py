"""Add consistency_checks table.

Revision ID: 0013_add_consistency_checks
Revises: 0012_add_stage1_review
Create Date: 2026-02-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_add_consistency_checks"
down_revision = "0012_add_stage1_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'check_type_enum') THEN
                CREATE TYPE check_type_enum AS ENUM ('duplicate', 'transfer_pair', 'anomaly');
            END IF;
        END$$;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'check_status_enum') THEN
                CREATE TYPE check_status_enum AS ENUM ('pending', 'approved', 'rejected', 'flagged');
            END IF;
        END$$;
    """)
    op.create_table(
        "consistency_checks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "check_type",
            sa.dialects.postgresql.ENUM(
                "duplicate", "transfer_pair", "anomaly", name="check_type_enum", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.dialects.postgresql.ENUM(
                "pending", "approved", "rejected", "flagged", name="check_status_enum", create_type=False
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("related_txn_ids", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("details", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("severity", sa.String(20), server_default="medium"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_consistency_checks_user_id", "consistency_checks", ["user_id"])
    op.create_index("ix_consistency_checks_status", "consistency_checks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_consistency_checks_status", table_name="consistency_checks")
    op.drop_index("ix_consistency_checks_user_id", table_name="consistency_checks")
    op.drop_table("consistency_checks")
    op.execute("DROP TYPE IF EXISTS check_status_enum")
    op.execute("DROP TYPE IF EXISTS check_type_enum")
