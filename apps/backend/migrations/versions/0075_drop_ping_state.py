"""Drop the ping_state demo table (#3011, slice 2 of the #3009 URL-surface diet).

The GET /ping route and the PingState model retired with the API-surface diet: no
client, job, or document consumed them. The table only held the demo toggle state.

Revision ID: 0075_drop_ping_state
Revises: 0074_statement_runs
Create Date: 2026-11-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0075_drop_ping_state"
down_revision: str | None = "0074_statement_runs"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_table("ping_state")


def downgrade() -> None:
    op.create_table(
        "ping_state",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("state", sa.String(length=10), nullable=False, server_default="ping"),
        sa.Column("toggle_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
