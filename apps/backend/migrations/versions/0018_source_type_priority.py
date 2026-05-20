"""Add source_type trust hierarchy values.

Revision ID: 0018_source_type_priority
Revises: 0017_investment_accounting
Create Date: 2026-05-20
"""

from alembic import op

revision = "0018_source_type_priority"
down_revision = "0017_investment_accounting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE journal_source_type_enum ADD VALUE IF NOT EXISTS 'user_confirmed'")
        op.execute("ALTER TYPE journal_source_type_enum ADD VALUE IF NOT EXISTS 'auto_matched'")
        op.execute("ALTER TYPE journal_source_type_enum ADD VALUE IF NOT EXISTS 'auto_parsed'")

    op.execute("UPDATE journal_entries SET source_type = 'auto_parsed' WHERE source_type = 'bank_statement'")


def downgrade() -> None:
    op.execute(
        "UPDATE journal_entries SET source_type = 'bank_statement' "
        "WHERE source_type IN ('user_confirmed', 'auto_matched', 'auto_parsed')"
    )
