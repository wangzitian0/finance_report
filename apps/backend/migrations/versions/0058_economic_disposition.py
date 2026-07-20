"""Make reconciliation disposition heads and transfer pairs persistent."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0058_economic_disposition"
down_revision = "0057_drop_confidence_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    disposition_kind = postgresql.ENUM(
        "journal_match",
        "transfer_leg",
        "reviewed_unmatched",
        name="reconciliation_disposition_kind_enum",
        create_type=False,
    )
    disposition_kind.create(op.get_bind(), checkfirst=True)
    pair_decision = postgresql.ENUM(
        "auto_paired",
        "reviewer_paired",
        name="reconciliation_transfer_pair_decision_enum",
        create_type=False,
    )
    pair_decision.create(op.get_bind(), checkfirst=True)
    pair_review = postgresql.ENUM(
        "paired",
        "pending_review",
        name="reconciliation_transfer_pair_review_state_enum",
        create_type=False,
    )
    pair_review.create(op.get_bind(), checkfirst=True)
    pair_leg_role = postgresql.ENUM(
        "out",
        "in",
        name="reconciliation_transfer_pair_leg_role_enum",
        create_type=False,
    )
    pair_leg_role.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "reconciliation_matches",
        sa.Column(
            "disposition_kind",
            disposition_kind,
            nullable=False,
            server_default="journal_match",
        ),
    )
    # Historical application-level pre-reads allowed multiple active rows.
    # Preserve every row, deterministically retain the newest head, and link
    # older active rows to that winner before making the invalid state
    # unrepresentable.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    first_value(id) OVER (
                        PARTITION BY atomic_txn_id
                        ORDER BY created_at DESC, id DESC
                    ) AS winner_id,
                    row_number() OVER (
                        PARTITION BY atomic_txn_id
                        ORDER BY created_at DESC, id DESC
                    ) AS position
                FROM reconciliation_matches
                WHERE superseded_by_id IS NULL
                  AND status <> 'superseded'::reconciliation_status_enum
            )
            UPDATE reconciliation_matches AS loser
            SET status = 'superseded'::reconciliation_status_enum,
                superseded_by_id = ranked.winner_id,
                updated_at = now()
            FROM ranked
            WHERE loser.id = ranked.id
              AND ranked.position > 1
            """
        )
    )
    op.create_index(
        "uq_reconciliation_matches_active_atomic_txn",
        "reconciliation_matches",
        ["atomic_txn_id"],
        unique=True,
        postgresql_where=sa.text("superseded_by_id IS NULL AND status <> 'superseded'::reconciliation_status_enum"),
    )
    op.create_table(
        "reconciliation_transfer_pairs",
        sa.Column("decision", pair_decision, nullable=False),
        sa.Column("review_state", pair_review, nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("score_breakdown", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "reconciliation_transfer_pair_legs",
        sa.Column("pair_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", pair_leg_role, nullable=False),
        sa.Column("disposition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["disposition_id"],
            ["reconciliation_matches.id"],
            name="reconciliation_transfer_pair_legs_disposition_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pair_id"],
            ["reconciliation_transfer_pairs.id"],
            name="reconciliation_transfer_pair_legs_pair_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("pair_id", "role"),
        sa.UniqueConstraint(
            "disposition_id",
            name="uq_reconciliation_transfer_pair_legs_disposition",
        ),
    )


def downgrade() -> None:
    op.drop_table("reconciliation_transfer_pair_legs")
    op.drop_table("reconciliation_transfer_pairs")
    op.drop_index(
        "uq_reconciliation_matches_active_atomic_txn",
        table_name="reconciliation_matches",
    )
    op.drop_column("reconciliation_matches", "disposition_kind")
    for enum_name in (
        "reconciliation_transfer_pair_review_state_enum",
        "reconciliation_transfer_pair_decision_enum",
        "reconciliation_transfer_pair_leg_role_enum",
        "reconciliation_disposition_kind_enum",
    ):
        postgresql.ENUM(name=enum_name).drop(op.get_bind(), checkfirst=True)
