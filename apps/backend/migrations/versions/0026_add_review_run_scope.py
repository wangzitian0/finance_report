"""add review run scope"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_add_review_run_scope"
down_revision = "0025_add_evidence_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reconciliation_matches", sa.Column("run_id", sa.String(length=128), nullable=True))
    op.create_index("idx_reconciliation_matches_run_id", "reconciliation_matches", ["run_id"])
    op.add_column("consistency_checks", sa.Column("run_id", sa.String(length=128), nullable=True))
    op.create_index("idx_consistency_checks_run_id", "consistency_checks", ["run_id"])


def downgrade() -> None:
    op.drop_index("idx_consistency_checks_run_id", table_name="consistency_checks")
    op.drop_column("consistency_checks", "run_id")
    op.drop_index("idx_reconciliation_matches_run_id", table_name="reconciliation_matches")
    op.drop_column("reconciliation_matches", "run_id")
