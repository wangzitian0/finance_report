"""Persist exact bank custody independently from account display names."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0062_bank_custody"
down_revision = "0061_txn_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bank_custody_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("institution", sa.String(100), nullable=False),
        sa.Column("account_last4", sa.String(4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "institution", "account_last4", "currency", name="uq_bank_custody_identity"),
    )
    op.create_index("ix_bank_custody_bindings_user_id", "bank_custody_bindings", ["user_id"])


def downgrade() -> None:
    raise RuntimeError(
        "Bank custody bindings preserve account identity; retain this additive schema when rolling back application code, or restore a verified pre-upgrade backup."
    )
