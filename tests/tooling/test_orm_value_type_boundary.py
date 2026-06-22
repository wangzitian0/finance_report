"""ORM value-type boundary guards (EPIC-012 AC12.35, #3 boundary push).

The read/model layer hands business code typed values (Money/Quantity) so services
stop pulling raw Decimal off rows and wrapping it ad-hoc. Raw columns remain the
storage/write boundary; business reads the typed accessors. This is the pilot on
ManagedPosition + investment_accounting; other models/services follow.
"""

import re
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]

# Business files where ManagedPosition money is fully migrated to typed accessors.
MIGRATED_MANAGED_POSITION_FILES = [
    "apps/backend/src/services/portfolio.py",
    "apps/backend/src/services/investment_accounting.py",
    "apps/backend/src/services/assets.py",
    "apps/backend/src/services/performance_report.py",
    "apps/backend/src/services/reporting/portfolio_market.py",
]
# A raw money-column READ: position.cost_basis / unrealized_pnl / realized_pnl that
# is not the typed accessor (`_money`), not a different column (`_method`), and not
# a write (`position.x = ...`, the allowed storage edge). The write lookahead
# matches a single `=` assignment regardless of whitespace, but not `==`/`!=`
# (those are comparisons, i.e. reads).
_RAW_MANAGED_POSITION_MONEY_READ = re.compile(
    r"position\.(?:cost_basis|unrealized_pnl|realized_pnl)(?!_money|_method)(?!\s*=(?!=))"
)


def _read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


@ac_proof(
    proof_id="test_managed_position_money_accessors",
    ac_ids=["AC12.35.1"],
    ci_tier="pr_ci",
)
def test_AC12_35_1_managed_position_exposes_typed_accessors():
    """AC12.35.1: ManagedPosition exposes Money/Quantity read accessors at the ORM boundary."""
    src = _read("apps/backend/src/models/layer3.py")
    assert "from src.money import Money" in src
    assert "from src.quantity import Quantity" in src
    for accessor in (
        "def cost_basis_money(self) -> Money",
        "def unrealized_pnl_money(self) -> Money",
        "def realized_pnl_money(self) -> Money",
        "def quantity_qty(self) -> Quantity",
    ):
        assert accessor in src, f"ManagedPosition must expose `{accessor}`"


@ac_proof(
    proof_id="test_investment_accounting_reads_typed",
    ac_ids=["AC12.35.2"],
    ci_tier="pr_ci",
)
def test_AC12_35_2_investment_accounting_reads_position_via_accessors():
    """AC12.35.2: investment accounting updates position state via the typed accessors,
    not by re-wrapping raw Decimal columns."""
    src = _read("apps/backend/src/services/investment_accounting.py")
    assert "position.cost_basis_money" in src
    assert "position.realized_pnl_money" in src
    assert "position.quantity_qty" in src
    # the raw-Decimal read patterns are gone (writes to the column stay as the boundary)
    assert "to_money(position.cost_basis" not in src
    assert "position.realized_pnl or Decimal" not in src
    assert "Quantity(position.quantity," not in src


@ac_proof(
    proof_id="test_portfolio_holdings_money_native",
    ac_ids=["AC12.35.3"],
    ci_tier="pr_ci",
)
def test_AC12_35_3_portfolio_holdings_value_flows_as_money():
    """AC12.35.3: portfolio holdings valuation flows as Money end-to-end via a
    Money-native FX convert + the ManagedPosition accessors (no Decimal FX branch)."""
    fx = _read("apps/backend/src/services/fx.py")
    assert "async def convert_money(" in fx, (
        "fx must expose a Money-native convert helper"
    )
    src = _read("apps/backend/src/services/portfolio.py")
    assert "fx.convert_money(" in src
    assert "position.cost_basis_money" in src
    assert "position.quantity_qty" in src
    assert "UnitPrice(latest_price" in src

    # reporting's portfolio valuation also flows Money via the same helpers
    market = _read("apps/backend/src/services/reporting/portfolio_market.py")
    assert "fx.convert_money(" in market
    assert "position.cost_basis_money" in market
    assert "position.quantity_qty" in market


@ac_proof(
    proof_id="test_managed_position_raw_reads_forbidden",
    ac_ids=["AC12.35.4"],
    ci_tier="pr_ci",
)
def test_AC12_35_4_no_raw_managed_position_money_reads_in_migrated_files():
    """AC12.35.4 (ratchet): the migrated business files read ManagedPosition money
    only via the typed accessors — no raw position.cost_basis/unrealized_pnl/
    realized_pnl reads remain (writes `position.x = ...` at the storage edge stay
    allowed). This forbids the old raw-Decimal pattern from creeping back."""
    offenders = {
        path: _RAW_MANAGED_POSITION_MONEY_READ.findall(_read(path))
        for path in MIGRATED_MANAGED_POSITION_FILES
        if _RAW_MANAGED_POSITION_MONEY_READ.search(_read(path))
    }
    assert not offenders, (
        f"raw ManagedPosition money reads must use accessors: {offenders}"
    )
