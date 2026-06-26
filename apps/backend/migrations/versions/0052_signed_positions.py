"""drop non-negative market_value/cost_basis constraints for short positions (#1448)

A margin/options brokerage account holds short positions — a directly-shorted
stock or a sold option — with negative quantity AND negative market value /
cost basis. The ``quantity`` columns were already unconstrained, but two CHECK
constraints inconsistently blocked the matching negative value and crashed the
import with a constraint violation (500). Dropping them makes signed (long/short)
positions first-class: a short reduces portfolio value instead of being rejected.
"""

from alembic import op

revision = "0052_signed_positions"
down_revision = "0051_add_currency_unresolved"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_atomic_positions_market_value_non_negative",
        "atomic_positions",
        type_="check",
    )
    op.drop_constraint(
        "ck_managed_positions_cost_basis_non_negative",
        "managed_positions",
        type_="check",
    )


def downgrade() -> None:
    # Precondition: no short positions exist. Re-imposing these CHECK constraints
    # fails if any atomic_positions.market_value or managed_positions.cost_basis is
    # already negative (CR on #1448) — which is expected, since you cannot downgrade
    # a database that has used the feature this migration enables. Purge/clamp those
    # rows out-of-band before downgrading; we do NOT delete financial data here.
    op.create_check_constraint(
        "ck_atomic_positions_market_value_non_negative",
        "atomic_positions",
        "market_value >= 0",
    )
    op.create_check_constraint(
        "ck_managed_positions_cost_basis_non_negative",
        "managed_positions",
        "cost_basis >= 0",
    )
