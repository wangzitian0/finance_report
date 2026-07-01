"""Narrow-waist guard gate (AC-money.23.1, migrated from EPIC-002 AC2.23.1 into the
money package roadmap; #1167 / #1172).

Locks the money standard against erosion: the money modules stay float-free and
every stack keeps a conformance suite. The hard test proves the guard actually
bites — it flags an injected violation and passes on the real tree.
"""

from pathlib import Path

from common.audit.money.guard import (
    float_violations,
    missing_conformance_suites,
    scan_text_for_float,
)
from common.testing.ac_proof import ac_proof

_CLEAN_SNIPPET = """
from decimal import Decimal
def f(amount: Decimal, currency: str) -> Decimal:
    if isinstance(amount, float):
        raise TypeError("no float")
    return amount
"""

_VIOLATION_SNIPPET = """
rate: float = 1.0  # money-shaped float at module level

def bad(amount: float, currency: str) -> float:  # money-shaped float pair
    total = float(amount)  # cast back to float
    return total

async def worse(*args: float, **kwargs: float) -> float:  # async + *args/**kwargs float
    return 0
"""


@ac_proof(
    proof_id="test_money_guard_flags_injected_violation",
    ac_ids=["AC-money.23.1"],
    ci_tier="pr_ci",
    issue="#1172",
)
def test_AC2_23_1_guard_flags_injected_float_violation():
    """AC-money.23.1: the guard reports money-shaped float on a violation, none on clean."""
    hits = scan_text_for_float(_VIOLATION_SNIPPET)
    assert hits, "guard must flag a money-shaped float violation"
    assert any("cast" in h for h in hits)
    assert any("annotation" in h for h in hits)
    # The clean snippet (which *rejects* float via isinstance) is not flagged.
    assert scan_text_for_float(_CLEAN_SNIPPET) == []


@ac_proof(
    proof_id="test_money_modules_are_float_free",
    ac_ids=["AC-money.23.1"],
    ci_tier="pr_ci",
    issue="#1172",
)
def test_AC2_23_1_money_modules_are_float_free():
    """AC-money.23.1: the real money modules contain no float in money type positions."""
    assert float_violations() == []


@ac_proof(
    proof_id="test_money_conformance_suite_per_stack",
    ac_ids=["AC-money.23.1"],
    ci_tier="pr_ci",
    issue="#1172",
)
def test_AC2_23_1_conformance_suite_present_in_every_stack():
    """AC-money.23.1: each stack keeps a conformance suite so the ends cannot drift."""
    assert missing_conformance_suites() == []


@ac_proof(
    proof_id="test_money_guard_reports_violation_with_path",
    ac_ids=["AC-money.23.1"],
    ci_tier="pr_ci",
    issue="#1172",
)
def test_AC2_23_1_float_violations_reports_offending_path(tmp_path: Path):
    """AC-money.23.1: float_violations surfaces an offending money-module file by path."""
    money_dir = tmp_path / "common" / "money"
    money_dir.mkdir(parents=True)
    (money_dir / "bad.py").write_text("def f(x: float) -> None:\n    return None\n")
    violations = float_violations(repo_root=tmp_path)
    assert any("common/money/bad.py" in v for v in violations)
