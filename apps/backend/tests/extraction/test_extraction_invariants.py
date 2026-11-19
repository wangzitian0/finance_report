from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from src.extraction import TransactionDirection
from src.extraction.base.validation import BALANCE_TOLERANCE, evaluate_statement_balance
from src.extraction.extension.deduplication import DeduplicationService

_BALANCED_CASES = [
    (Decimal("0.00"), [Decimal("100.00")], []),
    (Decimal("1000.00"), [Decimal("200.00"), Decimal("50.00")], [Decimal("75.00")]),
    (Decimal("-50.00"), [Decimal("500.00")], [Decimal("499.99")]),
    (Decimal("9999.99"), [], [Decimal("9999.99")]),
    (Decimal("123.45"), [Decimal("10.10"), Decimal("20.20"), Decimal("30.30")], [Decimal("5.05"), Decimal("15.15")]),
    (Decimal("1000000.00"), [Decimal("0.01")] * 50, [Decimal("0.02")] * 25),
]


def _make_statement(opening: Decimal, ins: list[Decimal], outs: list[Decimal]) -> dict:
    net = sum(ins, Decimal("0")) - sum(outs, Decimal("0"))
    txns = [{"amount": str(a), "direction": "IN"} for a in ins] + [{"amount": str(a), "direction": "OUT"} for a in outs]
    return {"opening_balance": str(opening), "closing_balance": str(opening + net), "transactions": txns}


def _eval_bal(d: dict) -> dict:
    return evaluate_statement_balance(
        opening=Decimal(str(d["opening_balance"])),
        closing=Decimal(str(d["closing_balance"])),
        currency=None,
        currency_balances=None,
        transactions=d["transactions"],
    )


def test_balance_chain_invariant_holds_and_rejects_broken_chains():
    for opening, ins, outs in _BALANCED_CASES:
        extracted = _make_statement(opening, ins, outs)
        expected_closing = opening + sum(ins, Decimal("0")) - sum(outs, Decimal("0"))
        assert (
            _eval_bal(extracted)["balance_valid"] is True
            and Decimal(str(extracted["closing_balance"])) == expected_closing
        )
        extracted["closing_balance"] = str(expected_closing + BALANCE_TOLERANCE + Decimal("1.00"))
        assert _eval_bal(extracted)["balance_valid"] is False

    base = _make_statement(Decimal("1000.00"), [Decimal("100.00")], [])
    computed = Decimal(str(base["closing_balance"]))
    assert all(
        _eval_bal({**base, "closing_balance": str(computed + delta)})["balance_valid"] is True
        for delta in (BALANCE_TOLERANCE, -BALANCE_TOLERANCE)
    )


def test_distinct_same_amount_rows_never_collapse():
    uid = UUID("00000000-0000-0000-0000-000000000001")

    def _hash(occ: int, bal: Decimal | None) -> str:
        return DeduplicationService.calculate_transaction_hash(
            user_id=uid,
            txn_date=date(2025, 1, 15),
            amount=Decimal("100.00"),
            direction=TransactionDirection.IN,
            description="SALARY",
            reference=None,
            balance_after=bal,
            occurrence_index=occ,
        )

    assert all(len({_hash(i, bal) for i in range(n)}) == n for n in range(1, 13) for bal in (None, Decimal("100.00")))
    assert all(_hash(0, bal) == _hash(0, bal) and _hash(3, bal) == _hash(3, bal) for bal in (None, Decimal("100.00")))
