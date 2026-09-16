"""Persist immutable opening stock and retain rejected matches as history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0060_opening_positions"
down_revision = "0059_source_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "opening_position_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("fx_rate", sa.Numeric(18, 6)),
        sa.Column("journal_entry_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("journal_entries.id")),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_decision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.UniqueConstraint("account_id", "version", name="uq_opening_position_account_version"),
    )
    op.create_index("ix_opening_position_records_user_id", "opening_position_records", ["user_id"])
    op.execute("""CREATE OR REPLACE FUNCTION guard_opening_position_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Opening position facts are immutable';
END; $$ LANGUAGE plpgsql""")
    op.execute("""CREATE TRIGGER opening_position_immutable BEFORE UPDATE OR DELETE ON opening_position_records
FOR EACH ROW EXECUTE FUNCTION guard_opening_position_immutable()""")
    op.drop_index("uq_reconciliation_matches_active_atomic_txn", table_name="reconciliation_matches")
    op.create_index(
        "uq_reconciliation_matches_active_atomic_txn",
        "reconciliation_matches",
        ["atomic_txn_id"],
        unique=True,
        postgresql_where=sa.text(
            "superseded_by_id IS NULL AND status NOT IN ('superseded'::reconciliation_status_enum, 'rejected'::reconciliation_status_enum)"
        ),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Revision 0060 preserves immutable opening and recovered rejection history; "
        "roll back application code without downgrading this database, or restore "
        "a verified pre-upgrade backup before an explicit database rollback."
    )
