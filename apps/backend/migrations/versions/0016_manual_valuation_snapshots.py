"""Add manual valuation snapshots.

Revision ID: 0016_manual_valuation_snapshots
Revises: 0015_ai_ui_feedback_audit
Create Date: 2026-05-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_manual_valuation_snapshots"
down_revision = "0015_ai_ui_feedback_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE manual_valuation_component_type_enum AS ENUM ("
        "'property_value', 'mortgage_balance', 'cpf_balance', 'long_term_savings', "
        "'tax_payable', 'tax_refund', 'insurance_cash_value', 'esop', 'rsu', "
        "'stock_options', 'other_asset', 'other_liability'"
        "); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE manual_valuation_liquidity_class_enum AS ENUM ("
        "'liquid', 'restricted', 'illiquid', 'liability'"
        "); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    op.create_table(
        "manual_valuation_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "component_type",
            postgresql.ENUM(
                "property_value",
                "mortgage_balance",
                "cpf_balance",
                "long_term_savings",
                "tax_payable",
                "tax_refund",
                "insurance_cash_value",
                "esop",
                "rsu",
                "stock_options",
                "other_asset",
                "other_liability",
                name="manual_valuation_component_type_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "liquidity_class",
            postgresql.ENUM(
                "liquid",
                "restricted",
                "illiquid",
                "liability",
                name="manual_valuation_liquidity_class_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recurrence_days", sa.Integer(), nullable=True),
        sa.Column("reminder_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id",
            "component_type",
            "source",
            "as_of_date",
            name="uq_manual_valuation_user_component_source_date",
        ),
    )
    op.create_index("ix_manual_valuation_snapshots_user_id", "manual_valuation_snapshots", ["user_id"])
    op.create_index(
        "ix_manual_valuation_snapshots_user_as_of",
        "manual_valuation_snapshots",
        ["user_id", "as_of_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_manual_valuation_snapshots_user_as_of", table_name="manual_valuation_snapshots")
    op.drop_index("ix_manual_valuation_snapshots_user_id", table_name="manual_valuation_snapshots")
    op.drop_table("manual_valuation_snapshots")
    op.execute("DROP TYPE IF EXISTS manual_valuation_liquidity_class_enum")
    op.execute("DROP TYPE IF EXISTS manual_valuation_component_type_enum")
