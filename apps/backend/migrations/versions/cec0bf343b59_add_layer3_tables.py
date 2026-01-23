"""add_layer3_tables"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "cec0bf343b59"
down_revision = "e40975f66f7f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # FX Rates (missed previously)
    op.create_table(
        "fx_rates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("quote_currency", sa.String(length=3), nullable=False),
        sa.Column("rate", sa.DECIMAL(precision=18, scale=6), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "base_currency", "quote_currency", "rate_date", name="uq_fx_rates_pair_date"
        ),
    )
    op.create_index(
        "idx_fx_rates_lookup",
        "fx_rates",
        ["base_currency", "quote_currency", "rate_date"],
        unique=False,
    )

    # Layer 3 Tables
    op.create_table(
        "classification_rules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False, comment="Monotonic version"),
        sa.Column("effective_date", sa.Date(), nullable=False, comment="Rule applies from date"),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("rule_name", sa.String(length=100), nullable=False),
        sa.Column(
            "rule_type",
            sa.Enum("keyword_match", "regex_match", "ml_model", name="rule_type_enum"),
            nullable=False,
        ),
        sa.Column("rule_config", postgresql.JSONB(), nullable=False, comment="Matching criteria"),
        sa.Column("tag_mappings", postgresql.JSONB(), nullable=True, comment="Tags to apply"),
        sa.Column("default_account_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["default_account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "rule_name", "version_number", name="uq_classification_rules_version"
        ),
    )

    op.create_table(
        "transaction_classification",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("atomic_txn_id", sa.UUID(), nullable=False),
        sa.Column("rule_version_id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "applied", "superseded", name="classification_status_enum"),
            nullable=False,
        ),
        sa.Column("superseded_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["atomic_txn_id"], ["atomic_transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["rule_version_id"], ["classification_rules.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["transaction_classification.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "atomic_txn_id", "rule_version_id", name="uq_txn_classification_version"
        ),
    )


def downgrade() -> None:
    op.drop_table("transaction_classification")
    op.drop_table("classification_rules")
    op.drop_index("idx_fx_rates_lookup", table_name="fx_rates")
    op.drop_table("fx_rates")

    op.execute("DROP TYPE IF EXISTS rule_type_enum")
    op.execute("DROP TYPE IF EXISTS classification_status_enum")
