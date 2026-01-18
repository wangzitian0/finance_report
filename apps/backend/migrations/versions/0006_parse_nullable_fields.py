"""allow nullable statement fields for parsing

Revision ID: 0005_statement_parsing_nullable_fields
Revises: 0004_add_name_to_users
Create Date: 2026-01-20 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_parse_nullable_fields"
down_revision = "0005_fix_txn_status_enum"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("bank_statements", "currency", existing_type=sa.String(length=3), nullable=True)
    op.alter_column("bank_statements", "period_start", existing_type=sa.Date(), nullable=True)
    op.alter_column("bank_statements", "period_end", existing_type=sa.Date(), nullable=True)
    op.alter_column(
        "bank_statements", "opening_balance", existing_type=sa.Numeric(18, 2), nullable=True
    )
    op.alter_column(
        "bank_statements", "closing_balance", existing_type=sa.Numeric(18, 2), nullable=True
    )
    op.alter_column(
        "bank_statements", "confidence_score", existing_type=sa.Integer(), nullable=True
    )
    op.alter_column(
        "bank_statements", "balance_validated", existing_type=sa.Boolean(), nullable=True
    )


def downgrade() -> None:
    # Handle NULL values before making columns non-nullable
    op.execute("UPDATE bank_statements SET currency = 'SGD' WHERE currency IS NULL")
    op.execute("UPDATE bank_statements SET period_start = '1970-01-01' WHERE period_start IS NULL")
    op.execute("UPDATE bank_statements SET period_end = '1970-01-01' WHERE period_end IS NULL")
    op.execute("UPDATE bank_statements SET opening_balance = 0 WHERE opening_balance IS NULL")
    op.execute("UPDATE bank_statements SET closing_balance = 0 WHERE closing_balance IS NULL")
    op.execute("UPDATE bank_statements SET confidence_score = 0 WHERE confidence_score IS NULL")
    op.execute("UPDATE bank_statements SET balance_validated = False WHERE balance_validated IS NULL")

    op.alter_column(
        "bank_statements", "balance_validated", existing_type=sa.Boolean(), nullable=False
    )
    op.alter_column(
        "bank_statements", "confidence_score", existing_type=sa.Integer(), nullable=False
    )
    op.alter_column(
        "bank_statements", "closing_balance", existing_type=sa.Numeric(18, 2), nullable=False
    )
    op.alter_column(
        "bank_statements", "opening_balance", existing_type=sa.Numeric(18, 2), nullable=False
    )
    op.alter_column("bank_statements", "period_end", existing_type=sa.Date(), nullable=False)
    op.alter_column("bank_statements", "period_start", existing_type=sa.Date(), nullable=False)
    op.alter_column("bank_statements", "currency", existing_type=sa.String(length=3), nullable=False)
