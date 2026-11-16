"""One live answer for each row and rule version; a superseded answer stays as history (#2994).

A re-ask appends a new answer and supersedes the old one, so the full unique key
`uq_txn_classification_version` (atomic_txn_id, rule_version_id) becomes a partial unique index with the same
name on the same columns, for the statuses draft and applied. The name stays, because the classify run reads it
from the driver error to tell the collision of two writers from any other integrity error. The upgrade changes
no row: the old key is stricter than the new index. The partial index serves a query only when the query proves
the status, and a query with a bound status cannot. So the upgrade also creates a plain index on the same columns:
the lookups by `atomic_txn_id` keep their index (without it the income statement scans the rows of other users). The
downgrade stops with an error while a row and a rule version have more than one answer, because the full key
cannot hold them.

Revision ID: 0076_txn_classif_live_unique
Revises: 0075_drop_ping_state
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076_txn_classif_live_unique"
down_revision: str | None = "0075_drop_ping_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "uq_txn_classification_version"
LOOKUP = "ix_txn_classification_txn_rule"
TABLE = "transaction_classification"
COLUMNS = ["atomic_txn_id", "rule_version_id"]


def upgrade() -> None:
    op.drop_constraint(NAME, TABLE, type_="unique")
    op.create_index(NAME, TABLE, COLUMNS, unique=True, postgresql_where=sa.text("status IN ('draft', 'applied')"))
    op.create_index(LOOKUP, TABLE, COLUMNS)


def downgrade() -> None:
    duplicates = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM (SELECT 1 FROM transaction_classification "
            "GROUP BY atomic_txn_id, rule_version_id HAVING count(*) > 1) AS grouped"
        )
    )
    if duplicates:
        raise RuntimeError(
            f"Downgrade stopped: {duplicates} row and rule version pairs have more than one answer. "
            "Delete the superseded answers of those pairs, then run the downgrade again."
        )
    op.drop_index(LOOKUP, table_name=TABLE)
    op.drop_index(NAME, table_name=TABLE)
    op.create_unique_constraint(NAME, TABLE, COLUMNS)
