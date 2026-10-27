"""Composite value-operation laws + conformance (EPIC-012 AC12.33).

Money predicates/aggregation and the Ratio zero-denominator fallback — the reusable
operations that let business code stay typed instead of re-deriving them as raw
Decimal glue.
"""

from decimal import Decimal

import pytest

from common.audit.money import CurrencyMismatchError, Money
from common.audit.money.conformance import load_vectors as load_money_vectors
from common.audit.ratio import FloatNotAllowedError, Ratio
from common.audit.ratio.conformance import load_vectors as load_ratio_vectors
from common.testing.ac_proof import ac_proof

MONEY = load_money_vectors()
RATIO = load_ratio_vectors()


# ── Money predicates + sum ──────────────────────────────────────────────
@ac_proof(proof_id="test_money_predicates", ac_ids=["AC-audit.33.1"], ci_tier="pr_ci")
def test_AC12_33_1_money_predicates_and_sum():
    """AC-audit.33.1: Money has is_zero/is_positive/is_negative and a typed sum."""
    assert Money.zero("USD").is_zero()
    assert Money(Decimal("0.01"), "USD").is_positive()
    assert Money(Decimal("-0.01"), "USD").is_negative()
    assert not Money.zero("USD").is_positive()

    total = Money.sum(
        [
            Money(Decimal("10.00"), "USD"),
            Money(Decimal("5.50"), "USD"),
            Money(Decimal("-2.00"), "USD"),
        ]
    )
    assert total == Money(Decimal("13.50"), "USD")
    assert Money.sum([], currency="SGD") == Money.zero("SGD")
    with pytest.raises(ValueError):
        Money.sum([])  # empty without currency is undefined
    with pytest.raises(CurrencyMismatchError):
        Money.sum([Money(Decimal("1"), "USD"), Money(Decimal("1"), "SGD")])


@ac_proof(
    proof_id="test_money_composite_conformance",
    ac_ids=["AC-audit.33.2"],
    ci_tier="pr_ci",
)
def test_AC12_33_2_money_composite_matches_standard():
    """AC-audit.33.2: Money predicates / sum reproduce the shared vectors."""
    for c in MONEY["predicates"]:
        m = Money(Decimal(c["amount"]), c["currency"])
        assert m.is_zero() == c["is_zero"], c
        assert m.is_positive() == c["is_positive"], c
        assert m.is_negative() == c["is_negative"], c
    for c in MONEY["sum"]:
        items = [Money(Decimal(a), ccy) for a, ccy in c["items"]]
        assert Money.sum(items, currency=c["currency"]) == Money(
            Decimal(c["expected"]), c["currency"]
        ), c


# ── Ratio fallback ──────────────────────────────────────────────────────
@ac_proof(
    proof_id="test_ratio_fraction_or_zero", ac_ids=["AC-audit.33.1"], ci_tier="pr_ci"
)
def test_AC12_33_1_ratio_fraction_or_zero():
    """AC-audit.33.1: Ratio.fraction_or_zero replaces zero-denominator branching."""
    assert Ratio.fraction_or_zero(2, 8) == Ratio.fraction(2, 8)
    assert Ratio.fraction_or_zero(5, 0) == Ratio.zero()
    # the no-float invariant holds on BOTH inputs even when whole is zero
    with pytest.raises(FloatNotAllowedError):
        Ratio.fraction_or_zero(0.1, 0)


@ac_proof(
    proof_id="test_ratio_fallback_conformance",
    ac_ids=["AC-audit.33.2"],
    ci_tier="pr_ci",
)
def test_AC12_33_2_ratio_fraction_or_zero_matches_standard():
    """AC-audit.33.2: Ratio.fraction_or_zero reproduces the shared vectors."""
    for c in RATIO["fraction_or_zero"]:
        got = Ratio.fraction_or_zero(Decimal(c["part"]), Decimal(c["whole"]))
        assert got.value == Decimal(c["expected"]), c
