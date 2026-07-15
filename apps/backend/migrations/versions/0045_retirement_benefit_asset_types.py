"""add retirement and benefit manual valuation component types"""

from alembic import op

revision = "0045_ret_benefit_assets"
down_revision = "0044_llm_config_per_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE manual_valuation_component_type_enum ADD VALUE IF NOT EXISTS 'retirement_account'")
    op.execute(
        "ALTER TYPE manual_valuation_component_type_enum ADD VALUE IF NOT EXISTS 'social_security_personal_account'"
    )
    op.execute("ALTER TYPE manual_valuation_component_type_enum ADD VALUE IF NOT EXISTS 'long_term_benefit_asset'")


def downgrade() -> None:
    # PostgreSQL enum value removal requires rebuilding dependent columns; leave
    # values in place to preserve existing valuation facts.
    pass
