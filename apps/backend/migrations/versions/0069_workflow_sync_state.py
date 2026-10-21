"""Store the source fingerprint of the last workflow derivation per user (#2583).

Workflow reads (`GET /workflow/status`, `GET /workflow/events`, `GET /notifications`)
derived events and package readiness on each request and wrote the result. The new
`workflow_sync_states` row keeps the fingerprint of the derivation inputs and the readiness
of the last derivation. A read with an equal fingerprint skips the derivation and writes nothing.
The table is new and the upgrade writes no data. The first read of each user fills its row.

Revision ID: 0069_workflow_sync_state
Revises: 0068_journal_line_position
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0069_workflow_sync_state"
down_revision: str | None = "0068_journal_line_position"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_sync_states",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("package_readiness", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("workflow_sync_states")
