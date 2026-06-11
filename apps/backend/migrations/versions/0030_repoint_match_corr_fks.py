"""finalize reconciliation/correction FKs onto atomic_transactions (Phase F)

Follows ``0029_drop_bank_statement_tables``. After the legacy
``bank_statement_transactions`` table is dropped (CASCADE), this revision:

* removes the now-orphaned ``check_match_target`` constraint and ``bank_txn_id``
  column from ``reconciliation_matches`` and makes ``atomic_txn_id`` NOT NULL
  (every live match now targets a Layer-2 ``AtomicTransaction``);
* repoints ``correction_logs.transaction_id`` at ``atomic_transactions.id`` by
  recreating its foreign key (the original FK to ``bank_statement_transactions``
  was dropped by the CASCADE in the prior revision).

No production data exists, so no rows need rewriting.
"""

from alembic import op

revision = "0030_repoint_match_corr_fks"
down_revision = "0029_drop_bank_statement_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # reconciliation_matches: drop the dual-target check + legacy column, then
    # require atomic_txn_id. The bank_txn_id FK was already removed by the
    # CASCADE in 0029; guard the rest with IF EXISTS for idempotency.
    op.execute("ALTER TABLE reconciliation_matches DROP CONSTRAINT IF EXISTS check_match_target")
    op.execute("ALTER TABLE reconciliation_matches DROP COLUMN IF EXISTS bank_txn_id")
    op.alter_column("reconciliation_matches", "atomic_txn_id", nullable=False)

    # correction_logs: repoint transaction_id onto atomic_transactions.
    op.execute("ALTER TABLE correction_logs DROP CONSTRAINT IF EXISTS correction_logs_transaction_id_fkey")
    op.create_foreign_key(
        "correction_logs_transaction_id_fkey",
        "correction_logs",
        "atomic_transactions",
        ["transaction_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Irreversible: the legacy bank_txn_id column and the original FK target
    # (bank_statement_transactions) no longer exist after 0029, so there is no
    # consistent state to restore. Downgrade is intentionally a no-op.
    pass
