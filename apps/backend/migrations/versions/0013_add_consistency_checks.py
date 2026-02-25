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
    op.execute("CREATE TYPE check_type_enum AS ENUM ('duplicate', 'transfer_pair', 'anomaly')")
    op.execute("CREATE TYPE check_status_enum AS ENUM ('pending', 'approved', 'rejected', 'flagged')")

    op.create_table(
        "consistency_checks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "check_type",
            sa.Enum("duplicate", "transfer_pair", "anomaly", name="check_type_enum"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", "flagged", name="check_status_enum"),
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
    op.drop_index("ix_consistency_checks_status")
    op.drop_index("ix_consistency_checks_user_id")
    op.drop_table("consistency_checks")
    op.execute("DROP TYPE check_status_enum")
    op.execute("DROP TYPE check_type_enum")
