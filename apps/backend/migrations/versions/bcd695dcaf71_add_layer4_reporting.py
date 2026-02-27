"""add_layer4_reporting"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "bcd695dcaf71"
down_revision = "cec0bf343b59"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "report_type",
            sa.Enum("balance_sheet", "income_statement", "cash_flow", name="report_type_enum"),
            nullable=False,
        ),
        sa.Column("as_of_date", sa.Date(), nullable=False, comment="Report end date"),
        sa.Column("start_date", sa.Date(), nullable=True, comment="Report start date (for ranges)"),
        sa.Column("rule_version_id", sa.UUID(), nullable=False),
        sa.Column(
            "report_data", postgresql.JSONB(), nullable=False, comment="Full report JSON structure"
        ),
        sa.Column(
            "is_latest", sa.Boolean(), nullable=False, comment="Is this the most recent generation?"
        ),
        sa.Column(
            "ttl", sa.DateTime(timezone=True), nullable=True, comment="Expiration time for cache"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["rule_version_id"], ["classification_rules.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "report_type", "as_of_date", "rule_version_id", name="uq_report_snapshot"
        ),
    )


def downgrade() -> None:
    op.drop_table("report_snapshots")
    op.execute("DROP TYPE IF EXISTS report_type_enum")
