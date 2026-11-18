from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.extraction import BankStatementStatus, DocumentSource
from src.extraction.extension._llm_led_gate import QUARANTINE_METRIC_KIND, LlmLedQuarantineReason, evaluate_llm_led_extraction_gate
from src.extraction.extension.service import ExtractionService
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from src.observability import INVARIANT_VIOLATION_KINDS

_bank_payload = lambda *, opening, closing, txns: {"institution": "UOB", "account_last4": "6789", "currency": "SGD", "period_start": "2025-01-01", "period_end": "2025-01-31", "opening_balance": opening, "closing_balance": closing, "transactions": txns}


async def _parse(tmp_path, payload: dict, *, collapse: int = 0, db=None, user_id=None):
    service, pdf = ExtractionService(), tmp_path / "stmt.pdf"
    pdf.write_bytes(b"dummy")
    with patch.object(service, "extract_financial_data", new=AsyncMock(return_value=payload)), patch("src.extraction.extension.service.count_within_document_dedup_collapse", return_value=collapse):
        return await service.parse_document(DocumentSource.resolve(path=pdf, content=pdf.read_bytes()), institution="UOB", user_id=user_id or uuid4(), db=db)


@pytest.mark.parametrize(
    ("payload", "collapse", "expected_valid", "expected_reason_prefix", "exact_reasons", "max_confidence"),
    [
        (_bank_payload(opening="1000.00", closing="9999.00", txns=[{"date": "2025-01-15", "description": "Salary", "amount": "100.00", "direction": "IN"}]), 0, False, LlmLedQuarantineReason.BALANCE_CHAIN_UNRECONCILED.value, None, None),
        (_bank_payload(opening="500.00", closing="100000.00", txns=[{"date": "2025-01-10", "description": "Fee", "amount": "5.00", "direction": "OUT"}]), 0, False, LlmLedQuarantineReason.BALANCE_CHAIN_UNRECONCILED.value, None, None),
        (_bank_payload(opening="2000.00", closing="500.00", txns=[{"date": "2025-01-20", "description": "Refund", "amount": "200.00", "direction": "IN"}]), 0, False, LlmLedQuarantineReason.BALANCE_CHAIN_UNRECONCILED.value, None, None),
        (_bank_payload(opening="0.00", closing="110.00", txns=[{"date": "2025-01-05", "description": "DEP A", "amount": "50.00", "direction": "IN"}, {"date": "2025-01-06", "description": "DEP B", "amount": "60.00", "direction": "IN"}]), 1, False, LlmLedQuarantineReason.DEDUP_CONSERVATION_VIOLATION.value, None, None),
        ({"institution": "UOB", "account_last4": "6789", "currency": "SGD", "period_start": "2025-01-01", "period_end": "2025-01-31", "opening_balance": "1000.00", "transactions": [{"date": "2025-01-15", "description": "Salary", "amount": "100.00", "direction": "IN"}]}, 0, None, None, ("Source is missing required facts: opening and closing balances",), Decimal("0.59")),
        (_bank_payload(opening="1000.00", closing="1100.00", txns=[{"date": "2025-01-15", "description": "Salary", "amount": "100.00", "direction": "IN"}]), 0, True, None, (), None),
    ],
)
async def test_AC20_9_llm_led_blocking_gate_parse_outcomes(tmp_path, payload: dict, collapse: int, expected_valid, expected_reason_prefix: str | None, exact_reasons, max_confidence) -> None:
    result = await _parse(tmp_path, payload, collapse=collapse)
    assert result.balance_validated is expected_valid
    assert expected_reason_prefix is None or any(r.startswith(expected_reason_prefix) for r in result.review_reasons)
    assert exact_reasons is None or result.review_reasons == exact_reasons
    assert max_confidence is None or result.confidence <= max_confidence


async def test_AC20_9_pure_gate_observability_and_persistence(tmp_path, db, test_user) -> None:
    dedup = evaluate_llm_led_extraction_gate(is_brokerage=False, balance_valid=True, within_doc_collapse=1)
    balance = evaluate_llm_led_extraction_gate(is_brokerage=False, balance_valid=False, within_doc_collapse=0)
    assert (
        dedup.reason, balance.reason,
        evaluate_llm_led_extraction_gate(is_brokerage=False, balance_valid=True, within_doc_collapse=0).quarantined,
        evaluate_llm_led_extraction_gate(is_brokerage=True, balance_valid=False, within_doc_collapse=0).quarantined,
        evaluate_llm_led_extraction_gate(is_brokerage=False, balance_valid=False, within_doc_collapse=0, balance_gate_exempt=True).quarantined,
        evaluate_llm_led_extraction_gate(is_brokerage=False, balance_valid=False, within_doc_collapse=1, balance_gate_exempt=True).reason,
    ) == (LlmLedQuarantineReason.DEDUP_CONSERVATION_VIOLATION, LlmLedQuarantineReason.BALANCE_CHAIN_UNRECONCILED, False, False, False, LlmLedQuarantineReason.DEDUP_CONSERVATION_VIOLATION)
    assert {v.reason for v in (balance, dedup)} == set(LlmLedQuarantineReason) and {v.metric_kind for v in (balance, dedup)} == set(QUARANTINE_METRIC_KIND.values()) == {k for k in INVARIANT_VIOLATION_KINDS if k.startswith("llm_led_gate_quarantine_")}
    for reason in LlmLedQuarantineReason:
        v = evaluate_llm_led_extraction_gate(is_brokerage=False, balance_valid=reason is not LlmLedQuarantineReason.BALANCE_CHAIN_UNRECONCILED, within_doc_collapse=1 if reason is LlmLedQuarantineReason.DEDUP_CONSERVATION_VIOLATION else 0)
        assert all(tok not in f"{v.reason.value} {v.message} {v.metric_kind}" for tok in ("UOB", "6789", "SGD", "DBS"))

    result = await _parse(tmp_path, _bank_payload(opening="1000.00", closing="9999.00", txns=[{"date": "2025-01-15", "description": "Salary", "amount": "100.00", "direction": "IN"}]), db=db, user_id=test_user.id)
    await db.commit()
    persisted = (await db.execute(select(StatementSummary).where(StatementSummary.user_id == test_user.id, StatementSummary.file_hash == result.source_content_digest))).scalar_one()
    assert (persisted.status, (await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id))).scalars().all()) == (BankStatementStatus.REJECTED, [])
