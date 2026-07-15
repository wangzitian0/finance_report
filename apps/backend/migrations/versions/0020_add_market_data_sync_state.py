"""add market data sync state table"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_add_market_data_sync_state"
down_revision = "0019_add_stock_prices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("market_data_sync_state"):
        op.create_table(
            "market_data_sync_state",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("kind", sa.String(length=10), nullable=False),
            sa.Column("scope", sa.String(length=50), nullable=False),
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_success_date", sa.Date(), nullable=False),
            sa.Column("last_observation_date", sa.Date(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("kind", "scope", name="uq_market_data_sync_state_kind_scope"),
        )
    op.execute("CREATE INDEX IF NOT EXISTS idx_market_data_sync_state_lookup ON market_data_sync_state (kind, scope)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_market_data_sync_state_lookup")
    op.drop_table("market_data_sync_state")
