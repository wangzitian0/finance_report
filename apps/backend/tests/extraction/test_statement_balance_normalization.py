"""Balance normalization of an extracted statement (#2987).

Evidence of the staging probe of 2026-11-12 (v0.2.64), read from the logs of the statements:
- The Monopoly card statement was rejected once and approved once from the same PDF. The rejected pass
  had a balance gap of 579.88, which is twice the signed net of the rows (289.94). The statement lists
  one currency; the model added a one-entry `balances` list, and that list blocked the card sign inversion.
- The ICICI statement prints a running balance for each of 100 rows. One row (1998.34, a credit) came back
  as a debit, the gap was 3996.68, and the statement was rejected in both passes.
"""

import copy
from decimal import Decimal

import pytest

from src.extraction.base.validation import (
    detect_balance_chain_break,
    normalize_statement_balance_payload,
    validate_balance,
)


def _card_payload(**extra) -> dict:
    """Monopoly shape: the card prints positive balances owed, the model reads purchases as OUT."""
    rows = [("IN", "412.16"), ("IN", "1.38"), ("OUT", "703.48")]
    return {
        "institution": "FOOBAR CREDIT CARD",
        "currency": "SGD",
        "opening_balance": "412.16",
        "closing_balance": "702.10",
        "transactions": [
            {
                "date": "2023-07-02",
                "description": f"row {i}",
                "amount": amount,
                "direction": direction,
                "currency": "SGD",
            }
            for i, (direction, amount) in enumerate(rows)
        ],
        **extra,
    }


def _running_balance_payload(spec: list[tuple[str, str]], opening: str) -> dict:
    """A bank statement whose every row prints the balance after it; `spec` holds the true direction and amount."""
    balance = Decimal(opening)
    transactions = []
    for index, (direction, amount) in enumerate(spec):
        balance += Decimal(amount) if direction == "IN" else -Decimal(amount)
        transactions.append(
            {
                "date": "2024-08-01",
                "description": f"row {index}",
                "amount": amount,
                "direction": direction,
                "balance_after": str(balance),
                "currency": "INR",
            }
        )
    return {
        "institution": "ICICI",
        "currency": "INR",
        "opening_balance": opening,
        "closing_balance": str(balance),
        "transactions": transactions,
    }


SPEC = [("IN", "100.00"), ("OUT", "30.00"), ("IN", "50.00"), ("OUT", "20.00"), ("IN", "10.00"), ("OUT", "5.00")]


def _directions(payload: dict) -> list[str]:
    return [txn["direction"] for txn in payload["transactions"]]


def test_AC_extraction_2987_13_a_one_entry_balances_list_does_not_block_the_card_sign_inversion():
    """AC-extraction.2987.13: A single-currency statement with a one-entry balances list reconciles like one without."""
    plain = normalize_statement_balance_payload(_card_payload())
    listed = normalize_statement_balance_payload(
        _card_payload(balances=[{"currency": "SGD", "opening": "412.16", "closing": "702.10"}])
    )
    assert validate_balance(plain)["balance_valid"]
    assert validate_balance(listed)["balance_valid"]
    assert (listed["opening_balance"], listed["closing_balance"]) == ("-412.16", "-702.10")
    assert "balances" not in listed


def test_AC_extraction_2987_14_a_balances_list_of_two_currencies_is_kept():
    """AC-extraction.2987.14: Dropping the one-entry list must not drop the list of a statement in two currencies."""
    payload = _card_payload(
        balances=[
            {"currency": "SGD", "opening": "412.16", "closing": "702.10"},
            {"currency": "USD", "opening": "10.00", "closing": "12.00"},
        ]
    )
    payload["transactions"][2]["currency"] = "USD"
    normalized = normalize_statement_balance_payload(payload)
    assert [bucket["currency"] for bucket in normalized["balances"]] == ["SGD", "USD"]


@pytest.mark.parametrize("flipped", [0, 2, 5])
def test_AC_extraction_2987_15_a_direction_that_the_running_balance_contradicts_is_repaired(flipped):
    """AC-extraction.2987.15: One wrong direction among rows with a running balance is set from the balance."""
    payload = _running_balance_payload(SPEC, "1000.00")
    truth = _directions(payload)
    payload["transactions"][flipped]["direction"] = "OUT" if truth[flipped] == "IN" else "IN"
    assert detect_balance_chain_break(payload["transactions"], opening_balance=Decimal("1000.00")) is not None
    normalized = normalize_statement_balance_payload(payload)
    assert _directions(normalized) == truth
    assert detect_balance_chain_break(normalized["transactions"], opening_balance=Decimal("1000.00")) is None
    assert validate_balance(normalized)["balance_valid"]


def test_AC_extraction_2987_16_a_statement_that_prints_balances_owed_keeps_its_directions():
    """AC-extraction.2987.16: When most rows disagree with the balance sign, the convention is inverted and nothing is flipped."""
    payload = _running_balance_payload(SPEC, "1000.00")
    for txn in payload["transactions"]:
        txn["direction"] = "OUT" if txn["direction"] == "IN" else "IN"
    before = _directions(payload)
    normalized = normalize_statement_balance_payload(copy.deepcopy(payload))
    assert _directions(normalized) == before


def test_AC_extraction_2987_17_a_row_whose_balance_step_differs_from_its_amount_keeps_its_direction():
    """AC-extraction.2987.17: A balance step that does not equal the amount proves nothing, so the direction stays."""
    payload = _running_balance_payload(SPEC, "1000.00")
    payload["transactions"][2]["balance_after"] = "1234.56"
    payload["transactions"][2]["direction"] = "OUT"
    normalized = normalize_statement_balance_payload(payload)
    assert normalized["transactions"][2]["direction"] == "OUT"


def test_AC_extraction_2987_18_rows_without_a_running_balance_keep_their_directions():
    """AC-extraction.2987.18: A statement with no balance_after column is not touched by the repair."""
    payload = _running_balance_payload(SPEC, "1000.00")
    for txn in payload["transactions"]:
        del txn["balance_after"]
    payload["transactions"][2]["direction"] = "OUT"
    before = _directions(payload)
    assert _directions(normalize_statement_balance_payload(payload)) == before
