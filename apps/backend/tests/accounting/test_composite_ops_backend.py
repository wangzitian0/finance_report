"""Backend composite value-operations conformance (EPIC-012 AC12.33)."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from common.testing.ac_proof import ac_proof

from src.audit.money import CurrencyMismatchError, Money
from src.audit.ratio import Ratio

pytestmark = pytest.mark.no_db

_ROOT = Path(__file__).resolve().parents[4]
_MONEY = json.loads((_ROOT / "common/audit/money/conformance/vectors.json").read_text())
_RATIO = json.loads((_ROOT / "common/audit/ratio/conformance/vectors.json").read_text())


@ac_proof(proof_id="test_backend_money_composite", ac_ids=["AC-audit.33.1"], ci_tier="pr_ci")
def test_AC12_33_1_backend_money_predicates_sum():
    """AC-audit.33.1: src.audit.money predicates and sum behave correctly."""
    assert Money.zero("USD").is_zero()
    assert Money(Decimal("0.01"), "USD").is_positive()
    assert Money(Decimal("-0.01"), "USD").is_negative()
    assert Money.sum([Money(Decimal("1.00"), "USD"), Money(Decimal("2.00"), "USD")]) == Money(Decimal("3.00"), "USD")
    with pytest.raises(CurrencyMismatchError):
        Money.sum([Money(Decimal("1"), "USD"), Money(Decimal("1"), "SGD")])


@ac_proof(proof_id="test_backend_composite_vectors", ac_ids=["AC-audit.33.2"], ci_tier="pr_ci")
def test_AC12_33_2_backend_composite_matches_standard():
    """AC-audit.33.2: the shipped backend reproduces the shared composite vectors."""
    for c in _MONEY["predicates"]:
        m = Money(Decimal(c["amount"]), c["currency"])
        assert (m.is_zero(), m.is_positive(), m.is_negative()) == (
            c["is_zero"],
            c["is_positive"],
            c["is_negative"],
        ), c
    for c in _MONEY["sum"]:
        items = [Money(Decimal(a), ccy) for a, ccy in c["items"]]
        assert Money.sum(items, currency=c["currency"]) == Money(Decimal(c["expected"]), c["currency"]), c
    for c in _RATIO["fraction_or_zero"]:
        assert Ratio.fraction_or_zero(Decimal(c["part"]), Decimal(c["whole"])).value == Decimal(c["expected"]), c
