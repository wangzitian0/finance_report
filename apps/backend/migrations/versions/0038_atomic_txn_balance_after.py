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


_DEDUP_COMMENT_NEW = (
    "SHA256(user_id|date|amount|dir|desc|ref|disambiguator); disambiguator=balance_after or #occurrence"
)
_DEDUP_COMMENT_OLD = "SHA256(user_id|date|amount|dir|desc|ref)"


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
    # Keep the dedup_hash column comment in sync with the model (now documents the disambiguator).
    op.alter_column(
        "atomic_transactions",
        "dedup_hash",
        existing_type=sa.String(64),
        existing_nullable=False,
        comment=_DEDUP_COMMENT_NEW,
        existing_comment=_DEDUP_COMMENT_OLD,
    )


def downgrade() -> None:
    op.alter_column(
        "atomic_transactions",
        "dedup_hash",
        existing_type=sa.String(64),
        existing_nullable=False,
        comment=_DEDUP_COMMENT_OLD,
        existing_comment=_DEDUP_COMMENT_NEW,
    )
    op.drop_column("atomic_transactions", "balance_after")
