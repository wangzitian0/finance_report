"""statement conflicts acknowledged

Add ``statement_summaries.conflicts_acknowledged_at`` so a Stage-1 reviewer can
confirm that the surfaced duplicate / transfer-pair candidates are intentional,
letting approval proceed instead of being permanently blocked (#962). NULL means
unacknowledged, which preserves the existing blocking behavior for every row.

Migration risk: low (additive nullable timestamp column, no backfill).
"""

import sqlalchemy as sa
from alembic import op

revision = "0039_conflicts_acknowledged"
down_revision = "a14bb9204a08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "statement_summaries",
        sa.Column(
            "conflicts_acknowledged_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When a reviewer confirmed the duplicate/transfer-pair candidates are intentional (#962)",
        ),
    )


def downgrade() -> None:
    op.drop_column("statement_summaries", "conflicts_acknowledged_at")
