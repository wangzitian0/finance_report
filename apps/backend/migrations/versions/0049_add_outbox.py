"""add the shared outbox table for the platform transactional-outbox EventBus

Creates ONE shared table ``outbox`` owned by the ``platform`` package: every
producer that emits a domain event through the ``OutboxEventBus`` INSERTs a row
here in its own transaction (atomic with the domain state change), and the
``OutboxRelay`` later reads committed ``pending`` rows in id order and dispatches
them post-commit. The ``(status, id)`` index backs the relay's "oldest pending,
in order" drain query so it never scans published history.

``status`` is plain text (not a ``sa.Enum``) so adding a future lifecycle state
needs no enum migration; the relay only queries ``status = 'pending'``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0049_add_outbox"
down_revision = "0048_counter_tally"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("source_pkg", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_outbox"),
    )
    op.create_index("ix_outbox_status_id", "outbox", ["status", "id"])


def downgrade() -> None:
    op.drop_index("ix_outbox_status_id", table_name="outbox")
    op.drop_table("outbox")
