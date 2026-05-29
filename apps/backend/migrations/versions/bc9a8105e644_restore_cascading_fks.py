"""Restore cascading FKs"""

import sqlalchemy as sa
from alembic import op

revision = "bc9a8105e644"
down_revision = "0014_add_correction_logs"
branch_labels = None
depends_on = None

# Tables that reference users.id but were missing ON DELETE CASCADE.
_USER_FK_TABLES = [
    "accounts",
    "atomic_positions",
    "atomic_transactions",
    "bank_statements",
    "chat_sessions",
    "classification_rules",
    "consistency_checks",
    "dividend_income",
    "journal_entries",
    "managed_positions",
    "market_data_override",
    "report_snapshots",
    "uploaded_documents",
]


def _fk_name(table: str) -> str:
    """Generate deterministic constraint name for user_id FK."""
    return f"fk_{table}_user_id_users"


def upgrade() -> None:
    # Add CASCADE FKs for user_id on all tables that reference users
    for table in _USER_FK_TABLES:
        op.create_foreign_key(_fk_name(table), table, "users", ["user_id"], ["id"], ondelete="CASCADE")

    # Fix journal_lines → journal_entries FK to add CASCADE
    op.drop_constraint("journal_lines_journal_entry_id_fkey", "journal_lines", type_="foreignkey")
    op.create_foreign_key(
        "fk_journal_lines_journal_entry_id_journal_entries",
        "journal_lines",
        "journal_entries",
        ["journal_entry_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Add column comments to correction_logs
    op.alter_column(
        "correction_logs",
        "original_category",
        existing_type=sa.VARCHAR(length=100),
        comment="AI-suggested category before correction",
        existing_nullable=True,
    )
    op.alter_column(
        "correction_logs",
        "corrected_category",
        existing_type=sa.VARCHAR(length=100),
        comment="User-corrected category",
        existing_nullable=False,
    )
    op.alter_column(
        "correction_logs",
        "transaction_description",
        existing_type=sa.TEXT(),
        comment="Cached transaction description for few-shot prompt building",
        existing_nullable=True,
    )


def downgrade() -> None:
    # Revert column comments
    op.alter_column(
        "correction_logs",
        "transaction_description",
        existing_type=sa.TEXT(),
        comment=None,
        existing_comment="Cached transaction description for few-shot prompt building",
        existing_nullable=True,
    )
    op.alter_column(
        "correction_logs",
        "corrected_category",
        existing_type=sa.VARCHAR(length=100),
        comment=None,
        existing_comment="User-corrected category",
        existing_nullable=False,
    )
    op.alter_column(
        "correction_logs",
        "original_category",
        existing_type=sa.VARCHAR(length=100),
        comment=None,
        existing_comment="AI-suggested category before correction",
        existing_nullable=True,
    )

    # Revert journal_lines FK
    op.drop_constraint("fk_journal_lines_journal_entry_id_journal_entries", "journal_lines", type_="foreignkey")
    op.create_foreign_key(
        "journal_lines_journal_entry_id_fkey", "journal_lines", "journal_entries", ["journal_entry_id"], ["id"]
    )

    # Drop user_id CASCADE FKs (in reverse order)
    for table in reversed(_USER_FK_TABLES):
        op.drop_constraint(_fk_name(table), table, type_="foreignkey")
