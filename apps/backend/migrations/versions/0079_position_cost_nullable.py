"""Make managed_positions.cost_basis nullable and clear the values that no purchase supports (#2920).

Revision ID: 0079_position_cost_nullable
Revises: 0078_outbox_dead_letter
Create Date: 2026-11-20

``reconcile_positions`` stored the snapshot market value as the cost basis. Such a
value is not a cost. This migration sets it to NULL for each position that has no
BUY row in ``investment_transactions``. A position with a BUY row keeps its value.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0079_position_cost_nullable"
down_revision: str | None = "0078_outbox_dead_letter"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "managed_positions",
        "cost_basis",
        existing_type=sa.Numeric(18, 2),
        nullable=True,
        comment="Total cost of the recorded purchases; NULL when no purchase is recorded",
        existing_comment="Total cost basis",
    )
    op.execute(
        """
        UPDATE managed_positions AS p
        SET cost_basis = NULL, unrealized_pnl = NULL
        WHERE NOT EXISTS (
            SELECT 1 FROM investment_transactions AS t
            WHERE t.position_id = p.id AND t.transaction_type::text = 'buy'
        )
        """
    )


def downgrade() -> None:
    # The cleared values were market values, not costs; the downgrade cannot restore them.
    op.execute("UPDATE managed_positions SET cost_basis = 0 WHERE cost_basis IS NULL")
    op.alter_column(
        "managed_positions",
        "cost_basis",
        existing_type=sa.Numeric(18, 2),
        nullable=False,
        comment="Total cost basis",
        existing_comment="Total cost of the recorded purchases; NULL when no purchase is recorded",
    )
