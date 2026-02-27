"""add_atomic_txn_id_to_matches"""

import sqlalchemy as sa
from alembic import op

revision = "e40975f66f7f"
down_revision = "0008_layer12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reconciliation_matches", sa.Column("atomic_txn_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_matches_atomic_txn",
        "reconciliation_matches",
        "atomic_transactions",
        ["atomic_txn_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_index(
        "idx_reconciliation_matches_atomic_txn",
        "reconciliation_matches",
        ["atomic_txn_id"],
    )

    op.alter_column("reconciliation_matches", "bank_txn_id", existing_type=sa.UUID(), nullable=True)

    op.create_check_constraint(
        "check_match_target",
        "reconciliation_matches",
        sa.text("bank_txn_id IS NOT NULL OR atomic_txn_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_constraint("check_match_target", "reconciliation_matches", type_="check")

    op.execute("DELETE FROM reconciliation_matches WHERE bank_txn_id IS NULL")

    op.alter_column("reconciliation_matches", "bank_txn_id", existing_type=sa.UUID(), nullable=False)

    op.drop_index("idx_reconciliation_matches_atomic_txn", "reconciliation_matches")
    op.drop_constraint("fk_matches_atomic_txn", "reconciliation_matches", type_="foreignkey")
    op.drop_column("reconciliation_matches", "atomic_txn_id")
