"""add immutable statement-result and reviewed-envelope facts (#1912)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0055_reviewed_stmt_envelope"
down_revision = "0054_trace_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_statement_summaries_user_id_id",
        "statement_summaries",
        ["user_id", "id"],
    )
    op.create_table(
        "statement_extraction_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("statement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("source_content_digest", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("producer_version", sa.String(length=200), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_trace_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(content_digest) = 64",
            name="ck_statement_extraction_results_content_digest_length",
        ),
        sa.CheckConstraint(
            "length(source_content_digest) = 64",
            name="ck_statement_extraction_results_source_digest_length",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "statement_id"],
            ["statement_summaries.user_id", "statement_summaries.id"],
            name="fk_statement_extraction_results_statement_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "statement_id",
            "content_digest",
            name="uq_statement_extraction_results_statement_digest",
        ),
        sa.UniqueConstraint(
            "user_id",
            "statement_id",
            "id",
            name="uq_statement_extraction_results_identity",
        ),
    )
    op.create_index(
        "idx_statement_extraction_results_statement_created",
        "statement_extraction_results",
        ["user_id", "statement_id", "created_at"],
    )
    op.create_index(
        "ix_statement_extraction_results_user_id",
        "statement_extraction_results",
        ["user_id"],
    )
    op.add_column(
        "statement_summaries",
        sa.Column(
            "current_extraction_result_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Current immutable StatementExtractionResultRecord",
        ),
    )
    op.create_foreign_key(
        "fk_statement_summaries_current_result",
        "statement_summaries",
        "statement_extraction_results",
        ["user_id", "id", "current_extraction_result_id"],
        ["user_id", "statement_id", "id"],
    )
    op.create_table(
        "reviewed_statement_envelopes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("statement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("opening_balance", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("closing_balance", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("command_digest", sa.String(length=64), nullable=False),
        sa.Column("review_trace_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("period_start <= period_end", name="ck_reviewed_statement_envelopes_period_order"),
        sa.CheckConstraint("length(currency) = 3", name="ck_reviewed_statement_envelopes_currency_length"),
        sa.CheckConstraint(
            "length(command_digest) = 64",
            name="ck_reviewed_statement_envelopes_command_digest_length",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "statement_id", "source_result_id"],
            [
                "statement_extraction_results.user_id",
                "statement_extraction_results.statement_id",
                "statement_extraction_results.id",
            ],
            name="fk_reviewed_statement_envelopes_source_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "statement_id", "supersedes_id"],
            [
                "reviewed_statement_envelopes.user_id",
                "reviewed_statement_envelopes.statement_id",
                "reviewed_statement_envelopes.id",
            ],
            name="fk_reviewed_statement_envelopes_supersedes_owner",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "statement_id",
            "command_digest",
            name="uq_reviewed_statement_envelopes_command",
        ),
        sa.UniqueConstraint(
            "user_id",
            "statement_id",
            "id",
            name="uq_reviewed_statement_envelopes_identity",
        ),
    )
    op.create_index(
        "idx_reviewed_statement_envelopes_current",
        "reviewed_statement_envelopes",
        ["user_id", "statement_id", "source_result_id", "created_at"],
    )
    op.create_index(
        "ix_reviewed_statement_envelopes_user_id",
        "reviewed_statement_envelopes",
        ["user_id"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_reviewed_statement_envelope_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Reviewed statement envelope facts are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER statement_extraction_results_append_only
        BEFORE UPDATE OR DELETE ON statement_extraction_results
        FOR EACH ROW EXECUTE FUNCTION reject_reviewed_statement_envelope_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER reviewed_statement_envelopes_append_only
        BEFORE UPDATE OR DELETE ON reviewed_statement_envelopes
        FOR EACH ROW EXECUTE FUNCTION reject_reviewed_statement_envelope_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER reviewed_statement_envelopes_append_only ON reviewed_statement_envelopes")
    op.execute("DROP TRIGGER statement_extraction_results_append_only ON statement_extraction_results")
    op.execute("DROP FUNCTION reject_reviewed_statement_envelope_mutation")
    op.drop_index("idx_reviewed_statement_envelopes_current", table_name="reviewed_statement_envelopes")
    op.drop_index("ix_reviewed_statement_envelopes_user_id", table_name="reviewed_statement_envelopes")
    op.drop_table("reviewed_statement_envelopes")
    op.drop_constraint(
        "fk_statement_summaries_current_result",
        "statement_summaries",
        type_="foreignkey",
    )
    op.drop_column("statement_summaries", "current_extraction_result_id")
    op.drop_index("idx_statement_extraction_results_statement_created", table_name="statement_extraction_results")
    op.drop_index("ix_statement_extraction_results_user_id", table_name="statement_extraction_results")
    op.drop_table("statement_extraction_results")
    op.drop_constraint("uq_statement_summaries_user_id_id", "statement_summaries", type_="unique")
