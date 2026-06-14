"""atomic transaction balance_after

Persist the statement running balance (``balance_after``) on Layer-2
``AtomicTransaction`` rows. The value is already consumed when computing the
dedup hash; storing it lets the Stage-1 conflict guard tell two real-but-identical
transactions apart (different running balance => distinct transactions, not a
duplicate candidate) instead of falsely blocking approval.

Migration risk: low (additive nullable column, no backfill). Existing rows keep
``balance_after = NULL``, which the guard treats as ambiguous (still flagged for
review) -- the pre-existing behavior.
"""

import sqlalchemy as sa
from alembic import op

revision = "0038_atomic_txn_balance_after"
down_revision = "0037_report_package_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "atomic_transactions",
        sa.Column(
            "balance_after",
            sa.Numeric(18, 2),
            nullable=True,
            comment="Statement running balance after this transaction; disambiguates real-but-identical rows",
        ),
    )


def downgrade() -> None:
    op.drop_column("atomic_transactions", "balance_after")
