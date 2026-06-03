"""add statement extraction metadata"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_stmt_extract_metadata"
down_revision = "0022_harden_workflow_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bank_statements",
        sa.Column("extraction_metadata", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bank_statements", "extraction_metadata")
