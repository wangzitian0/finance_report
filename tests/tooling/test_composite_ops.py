"""Composite value-operation laws + conformance (EPIC-012 AC12.33).

Money predicates/aggregation, Ratio zero-denominator fallback, and MoneyTolerance
matching — the reusable operations that let business code stay typed instead of
re-deriving them as raw Decimal glue.
"""

from decimal import Decimal

import pytest
from common.money import CurrencyMismatchError, Money, MoneyTolerance
from common.money.conformance import load_vectors as load_money_vectors
from common.ratio import Ratio
from common.ratio.conformance import load_vectors as load_ratio_vectors
from common.testing.ac_proof import ac_proof

MONEY = load_money_vectors()
RATIO = load_ratio_vectors()


# ── Money predicates + sum ──────────────────────────────────────────────
@ac_proof(proof_id="test_money_predicates", ac_ids=["AC12.33.1"], ci_tier="pr_ci")
def test_AC12_33_1_money_predicates_and_sum():
    """AC12.33.1: Money has is_zero/is_positive/is_negative and a typed sum."""
    assert Money.zero("USD").is_zero()
    assert Money(Decimal("0.01"), "USD").is_positive()
    assert Money(Decimal("-0.01"), "USD").is_negative()
    assert not Money.zero("USD").is_positive()

    total = Money.sum(
        [Money(Decimal("10.00"), "USD"), Money(Decimal("5.50"), "USD"), Money(Decimal("-2.00"), "USD")]
    )
    assert total == Money(Decimal("13.50"), "USD")
    assert Money.sum([], currency="SGD") == Money.zero("SGD")
    with pytest.raises(ValueError):
        Money.sum([])  # empty without currency is undefined
    with pytest.raises(CurrencyMismatchError):
        Money.sum([Money(Decimal("1"), "USD"), Money(Decimal("1"), "SGD")])


@ac_proof(proof_id="test_money_composite_conformance", ac_ids=["AC12.33.2"], ci_tier="pr_ci")
def test_AC12_33_2_money_composite_matches_standard():
    """AC12.33.2: Money predicates / sum / tolerance reproduce the shared vectors."""
    for c in MONEY["predicates"]:
        m = Money(Decimal(c["amount"]), c["currency"])
        assert m.is_zero() == c["is_zero"], c
        assert m.is_positive() == c["is_positive"], c
        assert m.is_negative() == c["is_negative"], c
    for c in MONEY["sum"]:
        items = [Money(Decimal(a), ccy) for a, ccy in c["items"]]
        assert Money.sum(items, currency=c["currency"]) == Money(Decimal(c["expected"]), c["currency"]), c
    for c in MONEY["tolerance"]:
        tol = MoneyTolerance(
            Money(Decimal(c["absolute"]), c["currency"]),
            Ratio.from_percent(Decimal(c["relative_percent"])),
        )
        got = tol.holds(Money(Decimal(c["actual"]), c["currency"]), Money(Decimal(c["expected"]), c["currency"]))
        assert got == c["holds"], c


# ── MoneyTolerance laws ─────────────────────────────────────────────────
@ac_proof(proof_id="test_money_tolerance", ac_ids=["AC12.33.1"], ci_tier="pr_ci")
def test_AC12_33_1_money_tolerance_absolute_relative_and_scaled():
    """AC12.33.1: MoneyTolerance bands on max(absolute, relative*|expected|) and scales."""
    tol = MoneyTolerance(Money(Decimal("0.01"), "USD"))  # pure absolute
    assert tol.holds(Money(Decimal("100.00"), "USD"), Money(Decimal("100.005"), "USD"))
    assert not tol.holds(Money(Decimal("100.00"), "USD"), Money(Decimal("100.02"), "USD"))
    # scaled widens the band
    assert tol.scaled(2).holds(Money(Decimal("100.00"), "USD"), Money(Decimal("100.02"), "USD"))
    # relative band dominates for large expected
    rel = MoneyTolerance(Money(Decimal("0.01"), "USD"), Ratio.from_percent(1))
    assert rel.holds(Money(Decimal("100.00"), "USD"), Money(Decimal("101.00"), "USD"))
    # cross-currency comparison is rejected
    with pytest.raises(CurrencyMismatchError):
        tol.holds(Money(Decimal("1"), "USD"), Money(Decimal("1"), "SGD"))


# ── Ratio fallback ──────────────────────────────────────────────────────
@ac_proof(proof_id="test_ratio_fraction_or_zero", ac_ids=["AC12.33.1"], ci_tier="pr_ci")
def test_AC12_33_1_ratio_fraction_or_zero_and_none():
    """AC12.33.1: Ratio.fraction_or_zero/_or_none replace zero-denominator branching."""
    assert Ratio.fraction_or_zero(2, 8) == Ratio.fraction(2, 8)
    assert Ratio.fraction_or_zero(5, 0) == Ratio.zero()
    assert Ratio.fraction_or_none(5, 0) is None
    assert Ratio.fraction_or_none(2, 8) == Ratio.fraction(2, 8)


@ac_proof(proof_id="test_ratio_fallback_conformance", ac_ids=["AC12.33.2"], ci_tier="pr_ci")
def test_AC12_33_2_ratio_fraction_or_zero_matches_standard():
    """AC12.33.2: Ratio.fraction_or_zero reproduces the shared vectors."""
    for c in RATIO["fraction_or_zero"]:
        got = Ratio.fraction_or_zero(Decimal(c["part"]), Decimal(c["whole"]))
        assert got.value == Decimal(c["expected"]), c
