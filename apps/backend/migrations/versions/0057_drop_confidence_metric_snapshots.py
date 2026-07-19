"""Drop the superseded source-type confidence metric series."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0057_drop_confidence_metrics"
down_revision = "0056_decision_anchored_journal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("confidence_metric_snapshots")


def downgrade() -> None:
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
