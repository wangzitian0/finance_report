"""Add versioned transaction identities without rewriting existing facts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0061_txn_identity"
down_revision = "0059_source_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "atomic_transaction_identities",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("identity_version", sa.String(8), nullable=False),
        sa.Column("identity_hash", sa.String(64), nullable=False),
        sa.Column("legacy_hash", sa.String(64), nullable=False),
        sa.Column("atomic_txn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("custody_scope", sa.String(80), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["atomic_txn_id"], ["atomic_transactions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "identity_version", "identity_hash"),
    )
    op.create_index("idx_atomic_identity_legacy", "atomic_transaction_identities", ["user_id", "legacy_hash"])
    op.create_index(
        "ix_atomic_transaction_identities_atomic_txn_id", "atomic_transaction_identities", ["atomic_txn_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_atomic_identity_legacy", table_name="atomic_transaction_identities")
    op.drop_index("ix_atomic_transaction_identities_atomic_txn_id", table_name="atomic_transaction_identities")
    op.drop_table("atomic_transaction_identities")
