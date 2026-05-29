"""add stock prices market data table"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_add_stock_prices"
down_revision = "0018_source_type_priority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("stock_prices"):
        op.create_table(
            "stock_prices",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("symbol", sa.String(length=20), nullable=False),
            sa.Column("price", sa.DECIMAL(precision=18, scale=6), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("price_date", sa.Date(), nullable=False),
            sa.Column("source", sa.String(length=50), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("symbol", "price_date", name="uq_stock_prices_symbol_date"),
        )
    op.execute("CREATE INDEX IF NOT EXISTS idx_stock_prices_lookup ON stock_prices (symbol, price_date)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_stock_prices_lookup")
    op.drop_table("stock_prices")
