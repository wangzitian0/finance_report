"""Balance normalization and chain break detection (#2987)."""

from __future__ import annotations

import copy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.extraction import StatementEvidenceType, StatementSourceType
from src.extraction.base.validation import (
    _derive_running_balance_endpoints,
    _safe_parse_decimal,
    detect_balance_chain_break,
    normalize_statement_balance_payload,
    validate_balance,
)
from src.extraction.extension.result_contract import statement_evidence_type
from src.reporting.extension.package_document import _is_bank_statement_contribution
from src.schemas.extraction import BalanceValidationResult

SPEC = [("IN", "100.00"), ("OUT", "30.00"), ("IN", "50.00"), ("OUT", "20.00"), ("IN", "10.00"), ("OUT", "5.00")]


def _card_payload(**extra) -> dict:
    rows = [("IN", "412.16"), ("IN", "1.38"), ("OUT", "703.48")]
    return {
        "institution": "FOOBAR CREDIT CARD", "currency": "SGD", "opening_balance": "412.16", "closing_balance": "702.10",
        "transactions": [{"date": "2023-07-02", "description": f"row {i}", "amount": a, "direction": d, "currency": "SGD"} for i, (d, a) in enumerate(rows)], **extra,
    }


def _running_balance_payload(spec: list[tuple[str, str]], opening: str) -> dict:
    balance, transactions = Decimal(opening), []
    for index, (direction, amount) in enumerate(spec):
        balance += Decimal(amount) if direction == "IN" else -Decimal(amount)
        transactions.append({"date": "2024-08-01", "description": f"row {index}", "amount": amount, "direction": direction, "balance_after": str(balance), "currency": "INR"})
    return {"institution": "ICICI", "currency": "INR", "opening_balance": opening, "closing_balance": str(balance), "transactions": transactions}


def _directions(payload: dict) -> list[str]:
    return [txn["direction"] for txn in payload["transactions"]]


def test_AC_extraction_2987_13_14_card_inversion_and_multicurrency_balances():
    plain = normalize_statement_balance_payload(_card_payload())
    listed = normalize_statement_balance_payload(_card_payload(balances=[{"currency": "SGD", "opening": "412.16", "closing": "702.10"}]))
    assert (validate_balance(plain)["balance_valid"], validate_balance(listed)["balance_valid"], listed["opening_balance"], listed["closing_balance"], "balances" in listed) == (True, True, "-412.16", "-702.10", False)

    payload = _card_payload(balances=[{"currency": "SGD", "opening": "412.16", "closing": "702.10"}, {"currency": "USD", "opening": "10.00", "closing": "12.00"}])
    payload["transactions"][2]["currency"] = "USD"
    assert [b["currency"] for b in normalize_statement_balance_payload(payload)["balances"]] == ["SGD", "USD"]


@pytest.mark.parametrize("flipped", [0, 2, 5])
def test_AC_extraction_2987_15_a_direction_that_the_running_balance_contradicts_is_repaired(flipped):
    payload = _running_balance_payload(SPEC, "1000.00")
    truth = _directions(payload)
    payload["transactions"][flipped]["direction"] = "OUT" if truth[flipped] == "IN" else "IN"
    assert detect_balance_chain_break(payload["transactions"], opening_balance=Decimal("1000.00")) is not None
    normalized = normalize_statement_balance_payload(payload)
    assert (_directions(normalized), detect_balance_chain_break(normalized["transactions"], opening_balance=Decimal("1000.00")), validate_balance(normalized)["balance_valid"]) == (truth, None, True)


def test_AC_extraction_2987_16_17_18_unrepaired_direction_cases():
    owed = _running_balance_payload(SPEC, "1000.00")
    for txn in owed["transactions"]:
        txn["direction"] = "OUT" if txn["direction"] == "IN" else "IN"
    before_owed = _directions(owed)
    assert _directions(normalize_statement_balance_payload(copy.deepcopy(owed))) == before_owed

    step_mismatch = _running_balance_payload(SPEC, "1000.00")
    step_mismatch["transactions"][2]["balance_after"], step_mismatch["transactions"][2]["direction"] = "1234.56", "OUT"
    assert normalize_statement_balance_payload(step_mismatch)["transactions"][2]["direction"] == "OUT"

    no_bal = _running_balance_payload(SPEC, "1000.00")
    for txn in no_bal["transactions"]:
        del txn["balance_after"]
    no_bal["transactions"][2]["direction"] = "OUT"
    before_nb = _directions(no_bal)
    assert _directions(normalize_statement_balance_payload(no_bal)) == before_nb


def test_running_balance_endpoints_evidence_type_and_chain_break_detector():
    broken = [{"amount": "100.00", "direction": "IN", "balance_after": "1100.00", "currency": "USD"}, {"amount": "50.00", "direction": "OUT", "balance_after": "900.00", "currency": "USD"}]
    valid = [{"amount": "100.00", "direction": "IN", "balance_after": "1100.00", "currency": "USD"}, {"amount": "50.00", "direction": "OUT", "balance_after": "1050.00", "currency": "USD"}]
    model = BalanceValidationResult(opening_balance=None, closing_balance=None, calculated_closing="100.00", opening_delta="0", closing_delta="100.00", opening_match=False, closing_match=False, validated_at="2025-06-30T00:00:00Z")
    b_ledger = SimpleNamespace(contribution_type="statement_source", payload=SimpleNamespace(source_result=SimpleNamespace(source_type=StatementSourceType.BROKERAGE, evidence_type=StatementEvidenceType.TRANSACTION_LEDGER)))
    b_pos = SimpleNamespace(contribution_type="statement_source", payload=SimpleNamespace(source_result=SimpleNamespace(source_type=StatementSourceType.BROKERAGE, evidence_type=StatementEvidenceType.POSITION_SNAPSHOT)))
    assert (
        _safe_parse_decimal(""), _safe_parse_decimal("not-a-number"), _safe_parse_decimal(True), normalize_statement_balance_payload("not-a-dict"),
        _derive_running_balance_endpoints(broken, currency="USD"), _derive_running_balance_endpoints(valid, opening_balance=Decimal("1000.00"), closing_balance=Decimal("9999.00"), currency="USD"),
        model.opening_balance, statement_evidence_type(is_brokerage=True, provider_payload={"transactions": valid}, positions=[]),
        _is_bank_statement_contribution(b_ledger), _is_bank_statement_contribution(b_pos), _is_bank_statement_contribution(SimpleNamespace(contribution_type="valuation")),
    ) == (None, None, None, "not-a-dict", None, None, None, StatementEvidenceType.TRANSACTION_LEDGER, True, False, False)

    clean = _running_balance_payload([("IN", "500.00"), ("OUT", "200.00"), ("IN", "300.00")], "1000.00")["transactions"]
    dropped = [{"date": "2025-01-05", "amount": "500.00", "direction": "IN", "balance_after": "1500.00"}, {"date": "2025-01-20", "amount": "300.00", "direction": "IN", "balance_after": "1300.00"}]
    dec_txns = [{"date": "2025-01-05", "amount": "0.10", "direction": "IN", "balance_after": "1000.10"}, {"date": "2025-01-06", "amount": "0.20", "direction": "IN", "balance_after": "1000.35"}]
    brk = detect_balance_chain_break(dropped)
    assert detect_balance_chain_break(clean) is None and brk is not None and (brk.index, brk.expected_balance, brk.observed_balance) == (1, Decimal("1800.00"), Decimal("1300.00"))
    assert detect_balance_chain_break(dec_txns, opening_balance=Decimal("1000.00")) is None
    dec_txns[1]["balance_after"] = "1000.80"
    assert detect_balance_chain_break(dec_txns, opening_balance=Decimal("1000.00")).index == 1
    assert detect_balance_chain_break([{"date": "2025-01-05", "amount": "500.00", "direction": "IN", "balance_after": "1400.00"}], opening_balance=Decimal("1000.00")).index == 0
