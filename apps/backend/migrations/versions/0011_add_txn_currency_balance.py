"""Add currency and balance_after to bank_statement_transactions.

Revision ID: 0011_add_txn_currency_balance
Revises: 0010_add_parsing_progress
Create Date: 2025-02-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_add_txn_currency_balance"
down_revision = "0010_add_parsing_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bank_statement_transactions", sa.Column("currency", sa.String(3), nullable=True))
    op.add_column("bank_statement_transactions", sa.Column("balance_after", sa.Numeric(18, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("bank_statement_transactions", "balance_after")
    op.drop_column("bank_statement_transactions", "currency")
