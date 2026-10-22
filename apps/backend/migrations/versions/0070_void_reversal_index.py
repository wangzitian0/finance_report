"""Index the void-reversal link of journal entries (#2617).

Each report statement excludes an entry that another entry points to as its void reversal:
`NOT EXISTS (SELECT 1 FROM journal_entries v WHERE v.void_reversal_entry_id = journal_entries.id)`.
The column had no index. The anti-join scanned the journal entries of all users in each report
statement, so a report read grew with the data of other users. The foreign key of the column
(`ON DELETE RESTRICT`) also scanned the table at each entry delete.

The index is partial. A void entry is rare, so the index stays small, and a normal insert does not
write to it. The upgrade adds an index only and changes no row. `CREATE INDEX` blocks writes to
`journal_entries` while it runs. The build time is in the order of seconds for 10^5 entries.

Revision ID: 0070_void_reversal_index
Revises: 0069_workflow_sync_state
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070_void_reversal_index"
down_revision: str | None = "0069_workflow_sync_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_journal_entries_void_reversal_entry_id"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "journal_entries",
        ["void_reversal_entry_id"],
        postgresql_where=sa.text("void_reversal_entry_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        INDEX_NAME, table_name="journal_entries", postgresql_where=sa.text("void_reversal_entry_id IS NOT NULL")
    )
