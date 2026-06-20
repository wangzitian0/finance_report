"""add atomic valuation facts and stable classification storage (#1222)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0046_valuation_fact_storage"
down_revision = "0045_ret_benefit_assets"
branch_labels = None
depends_on = None


_L1 = (
    "cash",
    "marketable_investment",
    "retirement_and_benefit",
    "restricted_compensation",
    "real_estate",
    "liability",
    "other_asset",
    "non_asset",
)
_L2 = (
    "cash_deposit",
    "public_equity",
    "fund",
    "bond",
    "mandatory_retirement",
    "voluntary_retirement",
    "long_term_benefit",
    "equity_award",
    "property",
    "secured_liability",
    "unsecured_liability",
    "tax_liability",
    "protection_coverage",
    "unclassified",
)
_ECONOMIC_SIDE = ("asset", "liability", "non_asset")
_VALUATION_ROLE = ("net_worth_component", "coverage_amount", "informational")
_LIQUIDITY = ("liquid", "restricted", "illiquid", "liability")
_REVIEW_STATUS = ("pending", "approved", "rejected")


def upgrade() -> None:
    op.create_table(
        "atomic_valuation_facts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("raw_label", sa.Text(), nullable=False),
        sa.Column("issuer", sa.String(length=200), nullable=True),
        sa.Column("jurisdiction", sa.String(length=100), nullable=True),
        sa.Column("scheme_name", sa.String(length=200), nullable=True),
        sa.Column("source_document_anchor", postgresql.JSONB(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("evidence_spans", postgresql.JSONB(), nullable=True),
        sa.Column("dedup_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount >= 0", name="ck_atomic_valuation_facts_amount_non_negative"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "id", name="uq_atomic_valuation_facts_user_id_id"),
    )
    op.create_index(
        "uq_atomic_valuation_facts_user_dedup_hash",
        "atomic_valuation_facts",
        ["user_id", "dedup_hash"],
        unique=True,
    )
    op.create_index(
        "ix_atomic_valuation_facts_user_as_of",
        "atomic_valuation_facts",
        ["user_id", "as_of_date"],
    )
    op.create_index(
        "ix_atomic_valuation_facts_user_id",
        "atomic_valuation_facts",
        ["user_id"],
    )

    op.create_table(
        "valuation_classifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("valuation_fact_id", sa.UUID(), nullable=False),
        sa.Column("l1", sa.Enum(*_L1, name="valuation_l1_enum"), nullable=False),
        sa.Column("l2", sa.Enum(*_L2, name="valuation_l2_enum"), nullable=True),
        sa.Column(
            "economic_side",
            sa.Enum(*_ECONOMIC_SIDE, name="valuation_economic_side_enum"),
            nullable=False,
        ),
        sa.Column(
            "valuation_role",
            sa.Enum(*_VALUATION_ROLE, name="valuation_role_enum"),
            nullable=False,
        ),
        sa.Column(
            "liquidity_class",
            sa.Enum(*_LIQUIDITY, name="valuation_liquidity_class_enum"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column(
            "review_status",
            sa.Enum(*_REVIEW_STATUS, name="valuation_review_status_enum"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("model_version", sa.String(length=120), nullable=True),
        sa.Column("prompt_version", sa.String(length=120), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("superseded_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_valuation_classifications_confidence_unit_interval",
        ),
        sa.CheckConstraint("version >= 1", name="ck_valuation_classifications_version_positive"),
        sa.ForeignKeyConstraint(
            ["user_id", "valuation_fact_id"],
            ["atomic_valuation_facts.user_id", "atomic_valuation_facts.id"],
            name="fk_valuation_classifications_user_fact",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["valuation_classifications.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_valuation_classifications_current_per_fact",
        "valuation_classifications",
        ["valuation_fact_id"],
        unique=True,
        postgresql_where=sa.text("superseded_by_id IS NULL"),
    )
    op.create_index(
        "ix_valuation_classifications_user_id",
        "valuation_classifications",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_table("valuation_classifications")
    op.drop_table("atomic_valuation_facts")
    for enum_name in (
        "valuation_review_status_enum",
        "valuation_liquidity_class_enum",
        "valuation_role_enum",
        "valuation_economic_side_enum",
        "valuation_l2_enum",
        "valuation_l1_enum",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
