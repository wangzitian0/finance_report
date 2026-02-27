"""add_managed_positions"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "76c3ccfe844b"
down_revision = "51aa128d8189"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "managed_positions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("asset_identifier", sa.String(length=100), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column(
            "cost_basis",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            comment="Total cost basis",
        ),
        sa.Column("acquisition_date", sa.Date(), nullable=False),
        sa.Column("disposal_date", sa.Date(), nullable=True),
        sa.Column("status", sa.Enum("active", "disposed", name="position_status_enum"), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("position_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("managed_positions")
    op.execute("DROP TYPE IF EXISTS position_status_enum")
