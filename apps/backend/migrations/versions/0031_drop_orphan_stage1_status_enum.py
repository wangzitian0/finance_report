"""drop orphaned stage1_status_enum type (issue #831 FIX #8)

The ``stage1_status_enum`` Postgres type was created by
``0012_add_stage1_review`` as a standalone ``CREATE TYPE`` for the now-dropped
``bank_statements.stage1_status`` column. When ``0029_drop_bank_statement_tables``
dropped the legacy tables it explicitly dropped the other three enums but missed
this one, and ``DROP TABLE ... CASCADE`` does not remove a free-standing enum
type. The result is an orphaned, unused type in the database (the live
``StatementSummary`` model uses the distinct ``statement_summary_stage1_status_enum``).

This revision is pure cleanup: it drops the orphan type. No column references it.
"""

from alembic import op

revision = "0031_drop_orphan_stage1_enum"
down_revision = "0030_repoint_match_corr_fks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TYPE IF EXISTS stage1_status_enum")


def downgrade() -> None:
    # Recreate the type with its original 0012 definition so the migration is
    # fully reversible. Nothing references it, so no column rebind is needed.
    op.execute(
        "CREATE TYPE stage1_status_enum AS ENUM "
        "('pending_review', 'approved', 'rejected', 'edited')"
    )
