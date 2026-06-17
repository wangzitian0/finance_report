"""Python side of the cross-language money conformance suite (#1167 / #1170).

Drives the Python reference implementation (``common/money``) off the SAME
language-neutral vectors the TypeScript frontend uses
(``common/money/conformance/vectors.json``). If the two ends ever disagree on a
rounding boundary, a conversion, or a currency validation, this test (or its TS
mirror) fails. See ``common/money/conformance/README.md``.
"""

from decimal import Decimal

import pytest
from common.money import Currency, InvalidCurrencyError, Money, convert
from common.money.conformance import load_vectors
from common.testing.ac_proof import ac_proof

VECTORS = load_vectors()


@ac_proof(
    proof_id="test_money_conformance_rounding",
    ac_ids=["AC2.20.1"],
    issue="#1170",
)
@pytest.mark.parametrize("case", VECTORS["rounding"], ids=lambda c: f"{c['amount']}/{c['rounding']}")
def test_AC2_20_1_conformance_rounding(case):
    """AC2.20.1: Python quantize matches the shared rounding standard."""
    got = Money(Decimal(case["amount"]), "USD").quantize(case["rounding"]).amount
    assert got == Decimal(case["expected"]), case


@ac_proof(
    proof_id="test_money_conformance_convert",
    ac_ids=["AC2.20.1"],
    issue="#1170",
)
@pytest.mark.parametrize("case", VECTORS["convert"], ids=lambda c: f"{c['amount']}*{c['rate']}")
def test_AC2_20_1_conformance_convert(case):
    """AC2.20.1: Python convert matches the shared FX standard."""
    result = convert(
        Money(Decimal(case["amount"]), case["from"]),
        Decimal(case["rate"]),
        to=case["to"],
        rounding=case["rounding"],
    )
    assert result.amount == Decimal(case["expected"]), case
    assert result.currency.code == case["to"], case


@ac_proof(
    proof_id="test_money_conformance_currency",
    ac_ids=["AC2.19.1"],
    issue="#1170",
)
def test_AC2_19_1_conformance_currency_validation():
    """AC2.19.1: Python Currency matches the shared normalise/reject standard."""
    for case in VECTORS["currency_normalize"]:
        assert Currency(case["input"]).code == case["expected"], case
    for bad in VECTORS["currency_invalid"]:
        with pytest.raises(InvalidCurrencyError):
            Currency(bad)


def test_money_quantum_matches_standard():
    """The reference quantum/default-rounding equal the declared standard."""
    from common.money import MONEY_QUANTUM

    assert str(MONEY_QUANTUM) == VECTORS["money_quantum"]
    assert VECTORS["default_rounding"] == "ROUND_HALF_EVEN"
