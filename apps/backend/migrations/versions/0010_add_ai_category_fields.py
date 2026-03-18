"""Add AI category fields to bank_statement_transactions.

Revision ID: 0010_ai_category
Revises: 5e7857c97b74
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_ai_category"
down_revision = "5e7857c97b74"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bank_statement_transactions",
        sa.Column("suggested_category", sa.String(100), nullable=True),
    )
    op.add_column(
        "bank_statement_transactions",
        sa.Column("category_confidence", sa.Numeric(3, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bank_statement_transactions", "category_confidence")
    op.drop_column("bank_statement_transactions", "suggested_category")
