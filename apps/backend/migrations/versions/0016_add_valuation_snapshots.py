"""add valuation snapshots"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_add_valuation_snapshots"
down_revision = "0015_ai_ui_feedback_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE valuation_component_type_enum AS ENUM ("
        "'bank_cash', 'brokerage_position', 'property', 'mortgage', "
        "'tax_payable_or_refund', 'salary_bonus_receivable', 'esop_rsu_option', "
        "'cpf_or_long_term_savings', 'insurance_cash_value', 'other_asset', 'other_liability'"
        "); EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE valuation_side_enum AS ENUM ('asset', 'liability'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE valuation_source_enum AS ENUM ('manual', 'imported', 'system'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE valuation_confidence_enum AS ENUM ('trusted', 'high', 'medium', 'low', 'estimated'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    if not inspector.has_table("valuation_snapshots"):
        op.create_table(
            "valuation_snapshots",
            sa.Column(
                "component_type",
                postgresql.ENUM(
                    "bank_cash",
                    "brokerage_position",
                    "property",
                    "mortgage",
                    "tax_payable_or_refund",
                    "salary_bonus_receivable",
                    "esop_rsu_option",
                    "cpf_or_long_term_savings",
                    "insurance_cash_value",
                    "other_asset",
                    "other_liability",
                    name="valuation_component_type_enum",
                    create_type=False,
                ),
                nullable=False,
            ),
            sa.Column("component_name", sa.String(length=120), nullable=False),
            sa.Column(
                "side",
                postgresql.ENUM("asset", "liability", name="valuation_side_enum", create_type=False),
                nullable=False,
            ),
            sa.Column("value", sa.Numeric(precision=18, scale=2), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("as_of_date", sa.Date(), nullable=False),
            sa.Column(
                "source",
                postgresql.ENUM("manual", "imported", "system", name="valuation_source_enum", create_type=False),
                nullable=False,
            ),
            sa.Column(
                "confidence",
                postgresql.ENUM(
                    "trusted",
                    "high",
                    "medium",
                    "low",
                    "estimated",
                    name="valuation_confidence_enum",
                    create_type=False,
                ),
                nullable=False,
            ),
            sa.Column("stale_after_days", sa.Integer(), nullable=False),
            sa.Column("include_in_total_net_worth", sa.Boolean(), nullable=False),
            sa.Column("include_in_liquid_net_worth", sa.Boolean(), nullable=False),
            sa.Column("restricted_until", sa.Date(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("snapshot_metadata", postgresql.JSONB(), nullable=True),
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    op.execute("CREATE INDEX IF NOT EXISTS ix_valuation_snapshots_user_id ON valuation_snapshots (user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_valuation_snapshots_component_type "
        "ON valuation_snapshots (component_type)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_valuation_snapshots_side ON valuation_snapshots (side)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_valuation_snapshots_as_of_date ON valuation_snapshots (as_of_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_valuation_snapshots_user_component_date "
        "ON valuation_snapshots (user_id, component_type, component_name, as_of_date DESC)"
    )


def downgrade() -> None:
    op.drop_index("ix_valuation_snapshots_user_component_date", table_name="valuation_snapshots")
    op.drop_index("ix_valuation_snapshots_as_of_date", table_name="valuation_snapshots")
    op.drop_index("ix_valuation_snapshots_side", table_name="valuation_snapshots")
    op.drop_index("ix_valuation_snapshots_component_type", table_name="valuation_snapshots")
    op.drop_index("ix_valuation_snapshots_user_id", table_name="valuation_snapshots")
    op.drop_table("valuation_snapshots")
    op.execute("DROP TYPE IF EXISTS valuation_confidence_enum")
    op.execute("DROP TYPE IF EXISTS valuation_source_enum")
    op.execute("DROP TYPE IF EXISTS valuation_side_enum")
    op.execute("DROP TYPE IF EXISTS valuation_component_type_enum")
