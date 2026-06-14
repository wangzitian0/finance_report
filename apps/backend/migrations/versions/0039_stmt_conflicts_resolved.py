"""statement stage1 conflicts resolved marker

Persist ``stage1_conflicts_resolved_at`` on ``statement_summaries`` (#962).

When a Stage-1 statement contains a duplicate or transfer-pair candidate, the
approval guard blocks it. Previously there was no way to record the reviewer's
decision ("these are genuinely distinct" / "this is a real transfer pair"), so a
statement with an inherent, legitimate conflict was permanently stuck in
``parsed``. This timestamp records that the reviewer resolved the candidates; the
guard honors it to unblock approval. It is cleared on reject/reparse so a fresh
transaction set must be re-reviewed.

Migration risk: low (additive nullable column, no backfill). Existing rows keep
``stage1_conflicts_resolved_at = NULL`` -- the pre-existing "unresolved" behavior.
"""

import sqlalchemy as sa
from alembic import op

revision = "0039_stmt_conflicts_resolved"
down_revision = "a14bb9204a08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "statement_summaries",
        sa.Column(
            "stage1_conflicts_resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the reviewer resolved Stage-1 duplicate/transfer-pair candidates (#962)",
        ),
    )


def downgrade() -> None:
    op.drop_column("statement_summaries", "stage1_conflicts_resolved_at")
