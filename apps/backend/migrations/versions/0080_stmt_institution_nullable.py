"""Make statement_summaries.institution optional and let a reviewed envelope state it (#3167).

Revision ID: 0080_stmt_institution_nullable
Revises: 0079_position_cost_nullable
Create Date: 2026-11-20

A model reply can state no institution. The statement then keeps its rows and stores
NULL, not an invented name. The reviewer states the institution in the envelope
confirmation, and ``reviewed_statement_envelopes.institution`` holds that value.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0080_stmt_institution_nullable"
down_revision: str | None = "0079_position_cost_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("statement_summaries", "institution", existing_type=sa.String(100), nullable=True)
    op.add_column("reviewed_statement_envelopes", sa.Column("institution", sa.String(100), nullable=True))


def downgrade() -> None:
    # The downgrade writes no invented institution. It stops while a statement has none.
    count = (
        op.get_bind().execute(sa.text("SELECT COUNT(*) FROM statement_summaries WHERE institution IS NULL")).scalar()
    )
    if count:
        raise RuntimeError(
            f"{count} statement_summaries rows have no institution. "
            "Confirm the institution of each statement, or delete the statement, then run the downgrade again."
        )
    op.drop_column("reviewed_statement_envelopes", "institution")
    op.alter_column("statement_summaries", "institution", existing_type=sa.String(100), nullable=False)
