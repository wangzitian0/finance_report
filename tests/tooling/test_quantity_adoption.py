"""Quantity adoption guards (EPIC-012 AC12.30).

The Quantity base package should become the public quantity narrow waist, not a
second helper living under money. Backend guards target the high-risk quantity
paths that previously owned local 6-dp helpers or naked zero checks.
"""

from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    return (REPO / path).read_text(encoding="utf-8")


@ac_proof(
    proof_id="test_quantity_frontend_adoption", ac_ids=["AC12.30.4"], ci_tier="pr_ci"
)
def test_AC12_30_4_frontend_quantity_formatting_is_not_exported_from_money():
    """AC12.30.4: formatQuantity is public from lib/quantity, not lib/money."""
    money_index = _read(Path("apps/frontend/src/lib/audit/money/index.ts"))
    quantity_index = _read(Path("apps/frontend/src/lib/audit/quantity/index.ts"))
    assert "formatQuantity" not in money_index
    assert "formatQuantity" in quantity_index

    call_sites = [
        Path("apps/frontend/src/components/portfolio/HoldingsTable.tsx"),
        Path("apps/frontend/src/app/(main)/assets/page.tsx"),
        Path("apps/frontend/src/app/(main)/portfolio/[ticker]/page.tsx"),
    ]
    for path in call_sites:
        src = _read(path)
        assert "@/lib/audit/quantity" in src, (
            f"{path} must import quantity formatting from lib/quantity"
        )
        assert "formatQuantity" in src


@ac_proof(
    proof_id="test_quantity_backend_adoption", ac_ids=["AC12.30.4"], ci_tier="pr_ci"
)
def test_AC12_30_4_backend_quantity_hot_paths_use_quantity_type():
    """AC12.30.4: targeted backend quantity paths use Quantity for quantity semantics."""
    investment = _read(Path("apps/backend/src/services/investment_accounting.py"))
    assert "from src.audit.quantity import Quantity" in investment
    assert (
        "trade_quantity = Quantity(quantity, INVESTMENT_QUANTITY_UNIT).quantize()"
        in investment
    )
    assert "trade_quantity.is_zero()" in investment
    assert "QUANTITY = Decimal(" not in investment
    assert "def _quantity(" not in investment
    assert "def _quantized_quantity(" not in investment
    assert "quantized_quantity_value" not in investment
    assert "quantity_is_zero" not in investment
    assert ".quantize(QUANTITY" not in investment
    assert "unit_price=_quantized_quantity" not in investment
    assert "unit_cost=_quantized_quantity" not in investment

    portfolio = _read(Path("apps/backend/src/services/portfolio.py"))
    assert "from src.audit.quantity import Quantity" in portfolio
    # Quantity now flows via the ManagedPosition.quantity_qty accessor (#3 boundary
    # push); still the Quantity value type, just read at the ORM boundary.
    assert "position_quantity = position.quantity_qty.quantize()" in portfolio
    assert "snapshot_quantity.is_zero()" in portfolio
    assert 'quantity == Decimal("0")' not in portfolio
    assert 'quantity != Decimal("0")' not in portfolio
