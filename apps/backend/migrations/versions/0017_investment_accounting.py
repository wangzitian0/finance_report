"""Add investment transaction accounting tables.

Revision ID: 0017_investment_accounting
Revises: 0016_manual_valuation_snapshots
Create Date: 2026-05-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_investment_accounting"
down_revision = "0016_manual_valuation_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE investment_transaction_type_enum AS ENUM ('buy', 'sell', 'dividend'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    op.create_table(
        "investment_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("journal_entry_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column(
            "transaction_type",
            postgresql.ENUM("buy", "sell", "dividend", name="investment_transaction_type_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("asset_identifier", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=True),
        sa.Column("unit_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("gross_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("fees", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("cost_basis", sa.Numeric(18, 2), nullable=True),
        sa.Column("realized_pnl", sa.Numeric(18, 2), nullable=True),
        sa.Column(
            "cost_basis_method",
            postgresql.ENUM("FIFO", "LIFO", "AvgCost", name="cost_basis_method_enum", create_type=False),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["position_id"], ["managed_positions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_investment_transactions_user_id", "investment_transactions", ["user_id"])
    op.create_index("ix_investment_transactions_position_id", "investment_transactions", ["position_id"])
    op.create_index("ix_investment_transactions_journal_entry_id", "investment_transactions", ["journal_entry_id"])
    op.create_index("ix_investment_transactions_transaction_date", "investment_transactions", ["transaction_date"])
    op.create_index("ix_investment_transactions_asset_identifier", "investment_transactions", ["asset_identifier"])

    op.create_table(
        "investment_lots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("opening_transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_identifier", sa.String(100), nullable=False),
        sa.Column("acquisition_date", sa.Date(), nullable=False),
        sa.Column("original_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("remaining_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("disposed_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["opening_transaction_id"], ["investment_transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["position_id"], ["managed_positions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_investment_lots_user_id", "investment_lots", ["user_id"])
    op.create_index("ix_investment_lots_position_id", "investment_lots", ["position_id"])
    op.create_index("ix_investment_lots_opening_transaction_id", "investment_lots", ["opening_transaction_id"])
    op.create_index("ix_investment_lots_asset_identifier", "investment_lots", ["asset_identifier"])
    op.create_index("ix_investment_lots_acquisition_date", "investment_lots", ["acquisition_date"])


def downgrade() -> None:
    op.drop_index("ix_investment_lots_acquisition_date", table_name="investment_lots")
    op.drop_index("ix_investment_lots_asset_identifier", table_name="investment_lots")
    op.drop_index("ix_investment_lots_opening_transaction_id", table_name="investment_lots")
    op.drop_index("ix_investment_lots_position_id", table_name="investment_lots")
    op.drop_index("ix_investment_lots_user_id", table_name="investment_lots")
    op.drop_table("investment_lots")

    op.drop_index("ix_investment_transactions_asset_identifier", table_name="investment_transactions")
    op.drop_index("ix_investment_transactions_transaction_date", table_name="investment_transactions")
    op.drop_index("ix_investment_transactions_journal_entry_id", table_name="investment_transactions")
    op.drop_index("ix_investment_transactions_position_id", table_name="investment_transactions")
    op.drop_index("ix_investment_transactions_user_id", table_name="investment_transactions")
    op.drop_table("investment_transactions")
    op.execute("DROP TYPE IF EXISTS investment_transaction_type_enum")
