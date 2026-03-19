"""Add correction_logs table for EPIC-018 Phase 2.

Revision ID: 0014_add_correction_logs
Revises: 0013_add_consistency_checks
Create Date: 2026-03-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0014_add_correction_logs"
down_revision = "0010_ai_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "correction_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bank_statement_transactions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_category", sa.String(100), nullable=True),
        sa.Column("corrected_category", sa.String(100), nullable=False),
        sa.Column("original_account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("corrected_account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("transaction_description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_correction_logs_user_id", "correction_logs", ["user_id"])
    op.create_index("ix_correction_logs_transaction_id", "correction_logs", ["transaction_id"])


def downgrade() -> None:
    op.drop_index("ix_correction_logs_transaction_id", table_name="correction_logs")
    op.drop_index("ix_correction_logs_user_id", table_name="correction_logs")
    op.drop_table("correction_logs")
