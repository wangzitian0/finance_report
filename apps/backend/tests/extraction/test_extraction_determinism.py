from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from src.extraction import BankStatementStatus, DocumentSource, Stage1Status
from src.extraction.base.validation import compute_confidence_score, route_by_threshold, validate_balance_explicit
from src.extraction.extension.service import ExtractionService
from tests.statement_ingestion import parse_and_load_statement_projection

RUNS = 8
_BANK_VALID = {
    "institution": "DBS", "account_last4": "1234", "currency": "SGD", "period_start": "2024-01-01", "period_end": "2024-01-31",
    "opening_balance": "1000.00", "closing_balance": "1500.00",
    "transactions": [
        {"date": "2024-01-10", "description": "Salary Deposit", "amount": "800.00", "direction": "IN", "reference": "SAL001", "balance_after": "1800.00"},
        {"date": "2024-01-20", "description": "Rent Payment", "amount": "300.00", "direction": "OUT", "reference": "RENT01", "balance_after": "1500.00"},
    ],
}
_BANK_BALANCE_INVALID = {**_BANK_VALID, "closing_balance": "9999.99"}
_BROKERAGE = {
    "institution": "Futu", "account_last4": "5678", "currency": "USD", "period_start": "2024-01-01", "period_end": "2024-01-31",
    "opening_balance": "0.00", "closing_balance": "0.00",
    "positions": [{"symbol": "AAPL", "quantity": "10", "market_value": "1900.00"}, {"symbol": "TSLA", "quantity": "5", "market_value": "1000.00"}],
    "transactions": [],
}


def _outcome_signature(statement, transactions) -> tuple:
    txn_sig = tuple(sorted((str(t.txn_date), str(t.amount), str(getattr(t, "direction", "")), t.description or "", t.reference or "", t.currency or "", str(t.balance_after) if t.balance_after is not None else "", t.dedup_hash) for t in transactions))
    return statement.confidence_score, statement.status, statement.validation_error, txn_sig


@pytest.mark.parametrize("payload", [_BANK_VALID, _BANK_BALANCE_INVALID, _BROKERAGE], ids=["bank_valid", "bank_balance_invalid", "brokerage"])
def test_scoring_and_routing_are_deterministic(payload):
    opening, closing = Decimal(payload["opening_balance"]), Decimal(payload["closing_balance"])
    net = sum(Decimal(t["amount"]) if t["direction"] == "IN" else -Decimal(t["amount"]) for t in payload["transactions"])
    results = [(s := compute_confidence_score(payload, b := validate_balance_explicit(opening, closing, net)), route_by_threshold(s, b["balance_valid"]), b["balance_valid"]) for _ in range(RUNS)]
    assert len(set(results)) == 1


async def _parse_once(db, user_id, payload, tag: str):
    service = ExtractionService()
    with patch.object(service, "extract_financial_data", return_value=payload):
        _, statement, txns = await parse_and_load_statement_projection(service, db=db, source=DocumentSource.resolve(path=Path(f"{tag}.pdf"), content=f"PDF-{tag}".encode()), institution=payload.get("institution"), user_id=user_id)
    await db.commit()
    return statement, txns


async def test_repeated_parse_determinism(db, test_user):
    sigs = [_outcome_signature(*(await _parse_once(db, test_user.id, _BANK_VALID, f"repro-{i}"))) for i in range(RUNS)]
    assert len(set(sigs)) == 1 and sigs[0][0] > 0

    for payload, expected in [(_BANK_BALANCE_INVALID, BankStatementStatus.REJECTED), (_BROKERAGE, BankStatementStatus.PARSED)]:
        statuses = {(await _parse_once(db, test_user.id, payload, f"route-{expected.value}-{i}"))[0].status for i in range(RUNS)}
        assert statuses == {expected}

    stmt, _ = await _parse_once(db, test_user.id, _BANK_BALANCE_INVALID, "balance-invalid-quarantine")
    assert (stmt.status, stmt.stage1_status, stmt.balance_validated) == (BankStatementStatus.REJECTED, Stage1Status.REJECTED, False)
    assert stmt.validation_error and "llm_led_balance_chain_unreconciled" in stmt.validation_error
