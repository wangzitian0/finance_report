"""Add retry and dead-letter columns to the transactional outbox table (#3155).

Revision ID: 0078_outbox_dead_letter
Revises: 0077_stmt_summary_sub_account
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0078_outbox_dead_letter"
down_revision: str | None = "0077_stmt_summary_sub_account"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbox",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "outbox",
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outbox", "last_error")
    op.drop_column("outbox", "attempt_count")
