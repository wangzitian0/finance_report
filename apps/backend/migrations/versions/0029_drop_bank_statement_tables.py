"""drop legacy bank_statement tables and enums (EPIC-011 Stage 3, Phase F)

Removes the legacy ``bank_statement_transactions`` and ``bank_statements`` ODS
tables — superseded by ``UploadedDocument`` (Layer-1) + ``StatementSummary``
(DWD conform) + ``AtomicTransaction`` (Layer-2) — along with the enum types that
only those tables used. No production data exists, so no backfill is required.

The drops use ``CASCADE`` so dependent foreign keys (``reconciliation_matches``
and ``correction_logs`` still point at ``bank_statement_transactions`` at this
revision) are removed automatically; the follow-up revision then tidies up the
orphaned columns/constraints on those tables.
"""

from alembic import op

revision = "0029_drop_bank_statement_tables"
down_revision = "0028_statement_summaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bank_statement_transactions CASCADE")
    op.execute("DROP TABLE IF EXISTS bank_statements CASCADE")

    op.execute("DROP TYPE IF EXISTS bank_statement_transaction_status_enum")
    op.execute("DROP TYPE IF EXISTS confidence_level_enum")
    op.execute("DROP TYPE IF EXISTS bank_statement_status_enum")


def downgrade() -> None:
    # Irreversible: the legacy ODS tables and their enum types are dropped with
    # no data migration. Recreating empty shells would not restore lineage, so
    # downgrade is intentionally a no-op.
    pass
