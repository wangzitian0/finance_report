"""Add parsing_progress to bank_statements."""

import sqlalchemy as sa
from alembic import op

revision = "0010_add_parsing_progress"
down_revision: str = "0009_fx_reval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bank_statements",
        sa.Column("parsing_progress", sa.Integer(), nullable=True, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("bank_statements", "parsing_progress")
