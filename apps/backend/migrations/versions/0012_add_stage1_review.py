"""Add stage1 review fields to bank_statements.

Revision ID: 0012_add_stage1_review
Revises: c955c65dcc1f
Create Date: 2026-02-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_add_stage1_review"
down_revision = "c955c65dcc1f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE stage1_status_enum AS ENUM ('pending_review', 'approved', 'rejected', 'edited')")

    op.add_column(
        "bank_statements",
        sa.Column(
            "stage1_status",
            sa.Enum("pending_review", "approved", "rejected", "edited", name="stage1_status_enum"),
            nullable=True,
        ),
    )
    op.add_column(
        "bank_statements",
        sa.Column("balance_validation_result", sa.dialects.postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "bank_statements",
        sa.Column("stage1_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "bank_statements",
        sa.Column("manual_opening_balance", sa.Numeric(18, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bank_statements", "manual_opening_balance")
    op.drop_column("bank_statements", "stage1_reviewed_at")
    op.drop_column("bank_statements", "balance_validation_result")
    op.drop_column("bank_statements", "stage1_status")
    op.execute("DROP TYPE stage1_status_enum")
