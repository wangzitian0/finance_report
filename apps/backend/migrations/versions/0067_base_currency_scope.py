"""Store the base currency per user and per journal entry (#2539).

`users.base_currency` holds the user's own base reporting currency. NULL means
the operator default in `app_config`, then the env default.
`journal_entries.base_currency` holds the base currency that validated the entry
at creation. Posting a draft uses it, so a later change of the effective value
does not invalidate the decision anchor of the draft.
Both columns are nullable and the upgrade writes no data. Rows from before this
revision keep NULL and keep the old behavior.

Revision ID: 0067_base_currency_scope
Revises: 0066_reconciled_void_guard
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067_base_currency_scope"
down_revision: str | None = "0066_reconciled_void_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("base_currency", sa.String(length=3), nullable=True))
    op.add_column("journal_entries", sa.Column("base_currency", sa.String(length=3), nullable=True))


def downgrade() -> None:
    op.drop_column("journal_entries", "base_currency")
    op.drop_column("users", "base_currency")
