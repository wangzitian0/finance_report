"""fx conversions: cross-currency transfer as a linked multi-leg event

Adds the additive ``fx_conversions`` linking table (#1123 AC2). A cross-currency
transfer (money leaves ``from_account`` in ``currency_from`` and arrives in
``to_account`` as ``currency_to`` at a conversion ``rate``) is one economic event
spanning two legs, not two independent income/expense transactions. The table
records the paired multi-leg event so the accounting layer can treat it as
net-zero for net worth (minus ``fee``) and attribute rate moves to revaluation
over time (via the ``fx_revaluation`` journal source type) rather than to the
conversion event.

Migration risk: low (new additive table, no backfill, no changes to existing
tables). ``rate`` is quoted as ``currency_from / currency_to`` matching
``services/fx.get_exchange_rate``.
"""

import sqlalchemy as sa
from alembic import op

revision = "0042_fx_conversions"
down_revision = "0041_stmt_currency_balances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fx_conversions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("from_account_id", sa.UUID(), nullable=False),
        sa.Column("to_account_id", sa.UUID(), nullable=False),
        sa.Column("amount_from", sa.DECIMAL(precision=18, scale=2), nullable=False),
        sa.Column("currency_from", sa.String(length=3), nullable=False),
        sa.Column("amount_to", sa.DECIMAL(precision=18, scale=2), nullable=False),
        sa.Column("currency_to", sa.String(length=3), nullable=False),
        sa.Column("rate", sa.DECIMAL(precision=18, scale=6), nullable=False),
        sa.Column("fee", sa.DECIMAL(precision=18, scale=2), nullable=False),
        sa.Column("fee_currency", sa.String(length=3), nullable=True),
        sa.Column("conversion_date", sa.Date(), nullable=False),
        sa.Column("from_journal_entry_id", sa.UUID(), nullable=True),
        sa.Column("to_journal_entry_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_from > 0", name="ck_fx_conversions_amount_from_positive"),
        sa.CheckConstraint("amount_to > 0", name="ck_fx_conversions_amount_to_positive"),
        sa.CheckConstraint("rate > 0", name="ck_fx_conversions_rate_positive"),
        sa.CheckConstraint("fee >= 0", name="ck_fx_conversions_fee_non_negative"),
        sa.CheckConstraint(
            "from_account_id <> to_account_id",
            name="ck_fx_conversions_distinct_accounts",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["to_journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fx_conversions_user_id", "fx_conversions", ["user_id"], unique=False)
    op.create_index("ix_fx_conversions_from_account_id", "fx_conversions", ["from_account_id"], unique=False)
    op.create_index("ix_fx_conversions_to_account_id", "fx_conversions", ["to_account_id"], unique=False)
    op.create_index(
        "idx_fx_conversions_user_date",
        "fx_conversions",
        ["user_id", "conversion_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_fx_conversions_user_date", table_name="fx_conversions")
    op.drop_index("ix_fx_conversions_to_account_id", table_name="fx_conversions")
    op.drop_index("ix_fx_conversions_from_account_id", table_name="fx_conversions")
    op.drop_index("ix_fx_conversions_user_id", table_name="fx_conversions")
    op.drop_table("fx_conversions")
