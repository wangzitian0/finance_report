"""Initial schema for finance report."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    account_type_enum = sa.Enum(
        "ASSET",
        "LIABILITY",
        "EQUITY",
        "INCOME",
        "EXPENSE",
        name="account_type_enum",
    )
    statement_status_enum = sa.Enum(
        "uploaded",
        "parsing",
        "parsed",
        "approved",
        "rejected",
        name="statement_status_enum",
    )
    confidence_enum = sa.Enum("high", "medium", "low", name="confidence_level_enum")
    bank_status_enum = sa.Enum(
        "pending",
        "matched",
        "unmatched",
        name="bank_transaction_status_enum",
    )
    journal_entry_status_enum = sa.Enum(
        "draft",
        "posted",
        "reconciled",
        "void",
        name="journal_entry_status_enum",
    )
    journal_source_enum = sa.Enum(
        "manual",
        "bank_statement",
        "system",
        name="journal_source_type_enum",
    )
    journal_line_direction_enum = sa.Enum(
        "DEBIT",
        "CREDIT",
        name="journal_line_direction_enum",
    )
    reconciliation_status_enum = sa.Enum(
        "auto_accepted",
        "pending_review",
        "accepted",
        "rejected",
        "superseded",
        name="reconciliation_status_enum",
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", account_type_enum, nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=True),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["parent_id"], ["accounts.id"]),
    )

    op.create_table(
        "statements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("institution", sa.String(length=100), nullable=False),
        sa.Column("account_last4", sa.String(length=4), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("opening_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("closing_balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", statement_status_enum, nullable=False),
        sa.Column("confidence_score", sa.Integer(), nullable=False),
        sa.Column("balance_validated", sa.Boolean(), nullable=False),
        sa.Column("validation_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
    )

    op.create_table(
        "account_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("statement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("txn_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("direction", sa.String(length=3), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("status", bank_status_enum, nullable=False),
        sa.Column("confidence", confidence_enum, nullable=False),
        sa.Column("confidence_reason", sa.Text(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["statement_id"], ["statements.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "journal_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("memo", sa.String(length=500), nullable=False),
        sa.Column("source_type", journal_source_enum, nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", journal_entry_status_enum, nullable=False),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("void_reversal_entry_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )

    op.create_table(
        "journal_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("journal_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", journal_line_direction_enum, nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("fx_rate", sa.Numeric(12, 6), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name="positive_amount"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
    )

    op.create_table(
        "reconciliation_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("bank_txn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "journal_entry_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("match_score", sa.Integer(), nullable=False),
        sa.Column(
            "score_breakdown",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", reconciliation_status_enum, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bank_txn_id"], ["account_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["reconciliation_matches.id"]),
    )

    op.create_table(
        "ping_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("toggle_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ping_state")
    op.drop_table("reconciliation_matches")
    op.drop_table("journal_lines")
    op.drop_table("journal_entries")
    op.drop_table("account_events")
    op.drop_table("statements")
    op.drop_table("accounts")
    op.drop_table("users")

    op.execute("DROP TYPE IF EXISTS reconciliation_status_enum")
    op.execute("DROP TYPE IF EXISTS journal_line_direction_enum")
    op.execute("DROP TYPE IF EXISTS journal_source_type_enum")
    op.execute("DROP TYPE IF EXISTS journal_entry_status_enum")
    op.execute("DROP TYPE IF EXISTS bank_transaction_status_enum")
    op.execute("DROP TYPE IF EXISTS confidence_level_enum")
    op.execute("DROP TYPE IF EXISTS statement_status_enum")
    op.execute("DROP TYPE IF EXISTS account_type_enum")
