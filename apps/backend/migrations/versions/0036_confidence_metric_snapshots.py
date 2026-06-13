"""confidence metric snapshots (North-Star series)

Additive append-only table recording the low-confidence-data proportion over
time (vision North-Star Metric / Axiom B, EPIC-018 AC18.12).

Migration risk: low (additive table, no backfill, no read-path cutover).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0036_confidence_metric_snapshots"
down_revision = "0035_manual_valuation_versioning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "confidence_metric_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("low_confidence_count", sa.Integer(), nullable=False),
        sa.Column("low_confidence_proportion", sa.Numeric(precision=6, scale=5), nullable=False),
        sa.Column(
            "tier_breakdown",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="confidence_metric_snapshots_user_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_confidence_metric_snapshots_user_id",
        "confidence_metric_snapshots",
        ["user_id"],
    )
    op.create_index(
        "ix_confidence_metric_snapshots_user_created",
        "confidence_metric_snapshots",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_confidence_metric_snapshots_user_created", table_name="confidence_metric_snapshots")
    op.drop_index("ix_confidence_metric_snapshots_user_id", table_name="confidence_metric_snapshots")
    op.drop_table("confidence_metric_snapshots")
