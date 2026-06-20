"""UnitPrice adoption guards (EPIC-012 AC12.32).

The UnitPrice base package should own the money-per-quantity semantics that
portfolio/market-data services used to re-derive as raw ``Decimal`` glue: the
``quantity * price`` extension, the ``total / quantity`` rate, and the 6-dp price
quantum. These guards stop the local helpers and the duplicated quantum from
returning.
"""

from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    return (REPO / path).read_text(encoding="utf-8")


@ac_proof(
    proof_id="test_unit_price_investment_adoption",
    ac_ids=["AC12.32.3"],
    ci_tier="pr_ci",
)
def test_AC12_32_3_investment_accounting_uses_unit_price():
    """AC12.32.3: investment accounting prices via UnitPrice, not local Decimal helpers."""
    src = _read(Path("apps/backend/src/services/investment_accounting.py"))
    assert "from src.unit_price import UnitPrice" in src
    # typed call sites replace the raw quantity*price / amount/quantity glue
    assert "buy_price * trade_quantity" in src
    assert "sell_price * trade_quantity" in src
    assert "UnitPrice.from_total(" in src
    # the duplicated local quantum + helper are gone
    assert "_quantized_unit_rate" not in src
    assert "UNIT_RATE_QUANTUM" not in src
    assert "trade_quantity.value * unit_price" not in src


@ac_proof(
    proof_id="test_unit_price_market_data_adoption",
    ac_ids=["AC12.32.3"],
    ci_tier="pr_ci",
)
def test_AC12_32_3_market_data_price_quantum_is_single_sourced():
    """AC12.32.3: market-data prices reuse the package quantum, not a local literal."""
    src = _read(Path("apps/backend/src/services/market_data.py"))
    assert "from src.unit_price import UNIT_PRICE_QUANTUM" in src
    assert "_PRICE_QUANT = UNIT_PRICE_QUANTUM" in src
