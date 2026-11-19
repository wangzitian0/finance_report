"""Support multiple sub-account StatementSummary rows per uploaded file_hash (#2983).

Revision ID: 0077_stmt_summary_sub_account
Revises: 0076_txn_classif_live_unique
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0077_stmt_summary_sub_account"
down_revision: str | None = "0076_txn_classif_live_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "statement_summaries"
OLD_CONSTRAINT = "uq_statement_summaries_user_file_hash"
NEW_CONSTRAINT = "uq_statement_summaries_user_file_hash_sub_account"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "sub_account_key",
            sa.String(length=64),
            nullable=False,
            server_default="",
            comment="Sub-account partition key within a consolidated document (empty for primary/single-account)",
        ),
    )
    op.drop_constraint(OLD_CONSTRAINT, TABLE, type_="unique")
    op.create_unique_constraint(NEW_CONSTRAINT, TABLE, ["user_id", "file_hash", "sub_account_key"])


def downgrade() -> None:
    duplicates = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM (SELECT 1 FROM statement_summaries "
            "GROUP BY user_id, file_hash HAVING count(*) > 1) AS grouped"
        )
    )
    if duplicates:
        raise RuntimeError(
            f"Downgrade stopped: {duplicates} (user_id, file_hash) group(s) hold multiple sub-account summaries. "
            "Delete or consolidate secondary sub-account statements, then run the downgrade again."
        )
    op.drop_constraint(NEW_CONSTRAINT, TABLE, type_="unique")
    op.create_unique_constraint(OLD_CONSTRAINT, TABLE, ["user_id", "file_hash"])
    op.drop_column(TABLE, "sub_account_key")
