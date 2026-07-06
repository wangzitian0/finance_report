"""Composite-operation adoption guards (EPIC-012 AC12.33).

The reusable composite operations should replace the hand-rolled glue at the
business call sites that motivated them, and the local helpers should not return.
"""

from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


@ac_proof(
    proof_id="test_ratio_fraction_or_zero_adoption",
    ac_ids=["AC-audit.33.3"],
    ci_tier="pr_ci",
)
def test_AC12_33_3_zero_denominator_branching_routes_through_ratio():
    """AC-audit.33.3: zero-denominator ratio branching uses Ratio.fraction_or_zero."""
    portfolio = _read("apps/backend/src/services/portfolio.py")
    assert "def _ratio_or_zero(" not in portfolio, (
        "local _ratio_or_zero helper must be retired"
    )
    assert "Ratio.fraction_or_zero(" in portfolio

    perf = _read("apps/backend/src/services/performance_report.py")
    assert "Ratio.fraction_or_zero(value, total_market_value)" in perf
    assert "else Ratio.zero()" not in perf

    stats = _read("apps/backend/src/services/reconciliation_stats.py")
    assert "Ratio.fraction_or_zero(matched, total)" in stats


@ac_proof(
    proof_id="test_money_predicates_sum_adoption",
    ac_ids=["AC-audit.33.3"],
    ci_tier="pr_ci",
)
def test_AC12_33_3_money_predicates_and_sum_adopted():
    """AC-audit.33.3: investment accounting uses Money predicates + Money.sum."""
    src = _read("apps/backend/src/portfolio/extension/accounting.py")
    assert "gross.is_positive()" in src
    assert "net.is_positive()" in src
    assert "Money.sum(" in src
    # the naked Decimal-zero positivity checks are gone
    assert 'if amount <= Decimal("0")' not in src
    assert 'if proceeds <= Decimal("0")' not in src
