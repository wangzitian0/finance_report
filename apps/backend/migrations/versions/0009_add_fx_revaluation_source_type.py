"""Add FX_REVALUATION to JournalEntrySourceType enum.

Revision ID: 0009_fx_reval
Revises: 76c3ccfe844b
Create Date: 2026-01-25

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_fx_reval"
down_revision: str = "76c3ccfe844b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add FX_REVALUATION value to the journal_source_type_enum
    # This enum was normalized in migration 0007 with explicit name
    op.execute("ALTER TYPE journal_source_type_enum ADD VALUE IF NOT EXISTS 'fx_revaluation'")


def downgrade() -> None:
    # PostgreSQL doesn't easily support removing enum values
    # The value will remain but be unused if this migration is rolled back
    pass
