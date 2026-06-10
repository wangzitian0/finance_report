"""add statement_summaries conform table (EPIC-011 PR-A)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0028_statement_summaries"
down_revision = "0027_merge_review_email_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "statement_summaries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("uploaded_document_id", sa.UUID(), nullable=True),
        sa.Column("file_hash", sa.String(length=64), nullable=False, comment="SHA256, canonical document join key"),
        sa.Column(
            "account_id",
            sa.UUID(),
            nullable=True,
            comment="Custody account (DIM conform); set at statement confirmation",
        ),
        sa.Column("institution", sa.String(length=100), nullable=False),
        sa.Column("account_last4", sa.String(length=4), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("opening_balance", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("closing_balance", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("manual_opening_balance", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "uploaded",
                "parsing",
                "parsed",
                "approved",
                "rejected",
                name="statement_summary_status_enum",
            ),
            nullable=False,
        ),
        sa.Column(
            "stage1_status",
            sa.Enum(
                "pending_review",
                "approved",
                "rejected",
                "edited",
                name="statement_summary_stage1_status_enum",
            ),
            nullable=True,
        ),
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        sa.Column("balance_validated", sa.Boolean(), nullable=True),
        sa.Column("validation_error", sa.Text(), nullable=True),
        sa.Column("balance_validation_result", postgresql.JSONB(), nullable=True),
        sa.Column("stage1_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extraction_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["uploaded_document_id"], ["uploaded_documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "file_hash", name="uq_statement_summaries_user_file_hash"),
    )
    op.create_index("idx_statement_summaries_user_account", "statement_summaries", ["user_id", "account_id"])


def downgrade() -> None:
    op.drop_index("idx_statement_summaries_user_account", table_name="statement_summaries")
    op.drop_table("statement_summaries")
    op.execute("DROP TYPE IF EXISTS statement_summary_status_enum")
    op.execute("DROP TYPE IF EXISTS statement_summary_stage1_status_enum")
