"""manual valuation append-only versioning

Adds an append-only version chain to manual_valuation_snapshots so that a
correction for an existing (user_id, component_type, source, as_of_date) appends
a new version and supersedes the prior one instead of editing the fact in place
(vision Axiom A). Uniqueness is moved to a partial unique index over current
heads (superseded_by_id IS NULL) so superseded history rows can accumulate.

Migration risk: medium (index/constraint change + additive columns). Existing
rows all become version 1 heads (superseded_by_id NULL); the partial unique
index cannot conflict because the prior full unique constraint already forbade
duplicate keys.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0035_manual_valuation_versioning"
down_revision = "0034_audit_anchor_ri"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "manual_valuation_snapshots",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "manual_valuation_snapshots",
        sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "manual_valuation_snapshots_superseded_by_id_fkey",
        "manual_valuation_snapshots",
        "manual_valuation_snapshots",
        ["superseded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Uniqueness now applies only to the current head per key, so corrections can
    # accumulate as superseded history rows.
    op.drop_constraint(
        "uq_manual_valuation_user_component_source_date",
        "manual_valuation_snapshots",
        type_="unique",
    )
    op.create_index(
        "uq_manual_valuation_user_component_source_date",
        "manual_valuation_snapshots",
        ["user_id", "component_type", "source", "as_of_date"],
        unique=True,
        postgresql_where=sa.text("superseded_by_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_manual_valuation_user_component_source_date",
        table_name="manual_valuation_snapshots",
    )
    op.create_unique_constraint(
        "uq_manual_valuation_user_component_source_date",
        "manual_valuation_snapshots",
        ["user_id", "component_type", "source", "as_of_date"],
    )
    op.drop_constraint(
        "manual_valuation_snapshots_superseded_by_id_fkey",
        "manual_valuation_snapshots",
        type_="foreignkey",
    )
    op.drop_column("manual_valuation_snapshots", "superseded_by_id")
    op.drop_column("manual_valuation_snapshots", "version")
