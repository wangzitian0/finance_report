"""add counter_tally for the counter platform package (per-(user, key) tallies)

Creates the storage for the ``counter`` package: one row per (user_id, key) with
a non-negative ``count``. The composite primary key (user_id, key) IS the unique
(user, key) constraint and the conflict target for the atomic upsert-increment
(``INSERT ... ON CONFLICT (user_id, key) DO UPDATE SET count = count + 1``).
"""

import sqlalchemy as sa
from alembic import op

revision = "0048_counter_tally"
down_revision = "0047_drop_valuation_fact_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "counter_tally",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("count", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("count >= 0", name="ck_counter_tally_count_non_negative"),
        sa.PrimaryKeyConstraint("user_id", "key", name="pk_counter_tally"),
    )
    op.create_index(
        "ix_counter_tally_key",
        "counter_tally",
        ["key"],
    )


def downgrade() -> None:
    op.drop_index("ix_counter_tally_key", table_name="counter_tally")
    op.drop_table("counter_tally")
