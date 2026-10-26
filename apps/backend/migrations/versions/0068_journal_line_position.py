"""Store the command position of each journal line (#2539).

The decision-anchor target of a manual draft hashes its lines in command order.
Posting recomputes the target from the stored rows. A select without ORDER BY
returns rows in physical order, and that order can differ from the insert order.
`journal_lines.line_no` holds the zero-based position, and the ORM loads the lines
of an entry in that order. The column is nullable and the upgrade writes no data.
Rows from before this revision keep NULL and keep the old behavior.

Revision ID: 0068_journal_line_position
Revises: 0067_base_currency_scope
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0068_journal_line_position"
down_revision: str | None = "0067_base_currency_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("journal_lines", sa.Column("line_no", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("journal_lines", "line_no")
