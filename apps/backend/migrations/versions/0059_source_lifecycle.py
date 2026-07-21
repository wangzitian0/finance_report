"""Add retired states for extraction-owned source lifecycle."""

from alembic import op

revision = "0059_source_lifecycle"
down_revision = "0058_economic_disposition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE statement_summary_status_enum ADD VALUE IF NOT EXISTS 'retired'")
    op.execute("ALTER TYPE document_status_enum ADD VALUE IF NOT EXISTS 'retired'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed without rebuilding the type.
    # Keeping an unused additive value is safer than rewriting source rows.
    pass
