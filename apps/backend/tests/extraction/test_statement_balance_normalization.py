"""Balance normalization and chain break detection (#2987)."""

from __future__ import annotations

import copy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.extraction import StatementEvidenceType, StatementSourceType
from src.extraction.base import validation as validation_mod
from src.extraction.base.validation import (
    _safe_parse_decimal,
    analyze_statement_balance_payload,
    detect_balance_chain_break,
    evaluate_statement_balance,
)
from src.extraction.extension.result_contract import statement_evidence_type
from src.reporting.extension.package_document import _is_bank_statement_contribution
from src.schemas.extraction import BalanceValidationResult


def _validate_normalized(payload: dict) -> dict:
    return evaluate_statement_balance(
        opening=_safe_parse_decimal(payload.get("opening_balance")),
        closing=_safe_parse_decimal(payload.get("closing_balance")),
        currency=payload.get("currency"),
        currency_balances=None,
        transactions=payload.get("transactions") or [],
    )


SPEC = [("IN", "100.00"), ("OUT", "30.00"), ("IN", "50.00"), ("OUT", "20.00"), ("IN", "10.00"), ("OUT", "5.00")]


def _card_payload(**extra) -> dict:
    rows = [("IN", "412.16"), ("IN", "1.38"), ("OUT", "703.48")]
    return {
        "institution": "FOOBAR CREDIT CARD",
        "currency": "SGD",
        "opening_balance": "412.16",
        "closing_balance": "702.10",
        "transactions": [
            {"date": "2023-07-02", "description": f"row {i}", "amount": a, "direction": d, "currency": "SGD"}
            for i, (d, a) in enumerate(rows)
        ],
        **extra,
    }


def _running_balance_payload(spec: list[tuple[str, str]], opening: str) -> dict:
    balance, transactions = Decimal(opening), []
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


def _directions(payload: dict) -> list[str]:
    return [txn["direction"] for txn in payload["transactions"]]


def test_AC_extraction_2987_13_14_card_inversion_and_multicurrency_balances():
    assert not hasattr(validation_mod, "normalize_statement_balance_payload")
    plain = analyze_statement_balance_payload(_card_payload()).payload
    listed = analyze_statement_balance_payload(
        _card_payload(balances=[{"currency": "SGD", "opening": "412.16", "closing": "702.10"}])
    ).payload
    assert (
        _validate_normalized(plain)["balance_valid"],
        _validate_normalized(listed)["balance_valid"],
        listed["opening_balance"],
        listed["closing_balance"],
        "balances" in listed,
    ) == (True, True, "-412.16", "-702.10", False)

    payload = _card_payload(
        balances=[
            {"currency": "SGD", "opening": "412.16", "closing": "702.10"},
            {"currency": "USD", "opening": "10.00", "closing": "12.00"},
        ]
    )
    payload["transactions"][2]["currency"] = "USD"
    assert [b["currency"] for b in analyze_statement_balance_payload(payload).payload["balances"]] == ["SGD", "USD"]


@pytest.mark.parametrize("flipped", [0, 2, 5])
def test_AC_extraction_2987_15_a_direction_that_the_running_balance_contradicts_is_repaired(flipped):
    payload = _running_balance_payload(SPEC, "1000.00")
    truth = _directions(payload)
    payload["transactions"][flipped]["direction"] = "OUT" if truth[flipped] == "IN" else "IN"
    assert detect_balance_chain_break(payload["transactions"], opening_balance=Decimal("1000.00")) is not None
    normalized = analyze_statement_balance_payload(payload).payload
    assert (
        _directions(normalized),
        detect_balance_chain_break(normalized["transactions"], opening_balance=Decimal("1000.00")),
        _validate_normalized(normalized)["balance_valid"],
    ) == (truth, None, True)


def test_AC_extraction_2987_16_17_18_unrepaired_direction_cases():
    owed = _running_balance_payload(SPEC, "1000.00")
    for txn in owed["transactions"]:
        txn["direction"] = "OUT" if txn["direction"] == "IN" else "IN"
    before_owed = _directions(owed)
    assert _directions(analyze_statement_balance_payload(copy.deepcopy(owed)).payload) == before_owed

    step_mismatch = _running_balance_payload(SPEC, "1000.00")
    step_mismatch["transactions"][2]["balance_after"], step_mismatch["transactions"][2]["direction"] = "1234.56", "OUT"
    assert analyze_statement_balance_payload(step_mismatch).payload["transactions"][2]["direction"] == "OUT"

    no_bal = _running_balance_payload(SPEC, "1000.00")
    for txn in no_bal["transactions"]:
        del txn["balance_after"]
    no_bal["transactions"][2]["direction"] = "OUT"
    before_nb = _directions(no_bal)
    assert _directions(analyze_statement_balance_payload(no_bal).payload) == before_nb


def test_running_balance_endpoints_evidence_type_and_chain_break_detector():
    valid = [
        {"amount": "100.00", "direction": "IN", "balance_after": "1100.00", "currency": "USD"},
        {"amount": "50.00", "direction": "OUT", "balance_after": "1050.00", "currency": "USD"},
    ]
    model = BalanceValidationResult(
        opening_balance=None,
        closing_balance=None,
        calculated_closing="100.00",
        opening_delta="0",
        closing_delta="100.00",
        opening_match=False,
        closing_match=False,
        validated_at="2025-06-30T00:00:00Z",
    )
    b_ledger = SimpleNamespace(
        contribution_type="statement_source",
        payload=SimpleNamespace(
            source_result=SimpleNamespace(
                source_type=StatementSourceType.BROKERAGE, evidence_type=StatementEvidenceType.TRANSACTION_LEDGER
            )
        ),
    )
    b_pos = SimpleNamespace(
        contribution_type="statement_source",
        payload=SimpleNamespace(
            source_result=SimpleNamespace(
                source_type=StatementSourceType.BROKERAGE, evidence_type=StatementEvidenceType.POSITION_SNAPSHOT
            )
        ),
    )
    assert (
        _safe_parse_decimal(""),
        _safe_parse_decimal("not-a-number"),
        _safe_parse_decimal(True),
        analyze_statement_balance_payload("not-a-dict").payload,
        model.opening_balance,
        statement_evidence_type(is_brokerage=True, provider_payload={"transactions": valid}, positions=[]),
        _is_bank_statement_contribution(b_ledger),
        _is_bank_statement_contribution(b_pos),
        _is_bank_statement_contribution(SimpleNamespace(contribution_type="valuation")),
    ) == (None, None, None, "not-a-dict", None, StatementEvidenceType.TRANSACTION_LEDGER, True, False, False)

    clean = _running_balance_payload([("IN", "500.00"), ("OUT", "200.00"), ("IN", "300.00")], "1000.00")["transactions"]
    dropped = [
        {"date": "2025-01-05", "amount": "500.00", "direction": "IN", "balance_after": "1500.00"},
        {"date": "2025-01-20", "amount": "300.00", "direction": "IN", "balance_after": "1300.00"},
    ]
    dec_txns = [
        {"date": "2025-01-05", "amount": "0.10", "direction": "IN", "balance_after": "1000.10"},
        {"date": "2025-01-06", "amount": "0.20", "direction": "IN", "balance_after": "1000.35"},
    ]
    brk = detect_balance_chain_break(dropped)
    assert (
        detect_balance_chain_break(clean) is None
        and brk is not None
        and (brk.index, brk.expected_balance, brk.observed_balance) == (1, Decimal("1800.00"), Decimal("1300.00"))
    )
    assert detect_balance_chain_break(dec_txns, opening_balance=Decimal("1000.00")) is None
    dec_txns[1]["balance_after"] = "1000.80"
    assert detect_balance_chain_break(dec_txns, opening_balance=Decimal("1000.00")).index == 1
    assert (
        detect_balance_chain_break(
            [{"date": "2025-01-05", "amount": "500.00", "direction": "IN", "balance_after": "1400.00"}],
            opening_balance=Decimal("1000.00"),
        ).index
        == 0
    )


async def test_AC_extraction_3112_missing_printed_opening_never_self_validates_or_auto_approves():
    """#3112: A statement without printed opening_balance must not derive opening from row 1 and mark balance_validated=True."""
    from pathlib import Path
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from src.extraction import DocumentSource
    from src.extraction.extension.service import ExtractionService

    icici_shaped = {
        "institution": "ICICI",
        "account_last4": "4321",
        "currency": "INR",
        "period_start": "2024-08-01",
        "period_end": "2024-08-31",
        "opening_balance": None,
        "closing_balance": "6764.58",
        "transactions": [
            {
                "date": "2024-08-01",
                "description": "Salary Credit XYZ Pvt Ltd",
                "amount": "1935.30",
                "direction": "OUT",
                "currency": "INR",
                "balance_after": "6864.58",
            },
            {
                "date": "2024-08-02",
                "description": "ATM Withdrawal",
                "amount": "100.00",
                "direction": "OUT",
                "currency": "INR",
                "balance_after": "6764.58",
            },
        ],
    }

    analysis = analyze_statement_balance_payload(copy.deepcopy(icici_shaped))
    assert analysis.printed_opening_balance is None
    assert analysis.payload.get("opening_balance") is None
    assert _validate_normalized(analysis.payload)["balance_valid"] is False

    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=copy.deepcopy(icici_shaped))
    result = await service.parse_document(
        DocumentSource.resolve(path=Path("icici.pdf"), content=b"icici-no-text"),
        institution="ICICI",
        user_id=uuid4(),
        file_type="pdf",
        account_id=uuid4(),
    )
    assert result.balance_validated is not True
    assert result.balances == ()
    assert "balances" in result.missing_required_facts
    assert result.confidence <= Decimal("0.59")


def test_AC_extraction_3112_multicurrency_without_printed_balances_stays_hint_only():
    """#3112: Multi-currency rows with balance_after but no printed balances must not synthesize printed balances."""
    payload = {
        "institution": "MultiBank",
        "currency": "SGD",
        "opening_balance": None,
        "closing_balance": None,
        "transactions": [
            {
                "date": "2025-01-01",
                "amount": "100.00",
                "direction": "IN",
                "currency": "SGD",
                "balance_after": "1100.00",
            },
            {"date": "2025-01-02", "amount": "50.00", "direction": "IN", "currency": "USD", "balance_after": "250.00"},
        ],
    }
    analysis = analyze_statement_balance_payload(copy.deepcopy(payload))
    assert analysis.printed_balances == ()
    assert analysis.payload.get("balances") is None
