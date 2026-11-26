from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from infra2_sdk.llm import DecodingSpec
from sqlalchemy import select

from src.config import settings
from src.extraction import BankStatementStatus, DocumentSource
from src.extraction.base.validation import _safe_parse_decimal, evaluate_statement_balance
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.extraction.orm.layer2 import AtomicTransaction
from src.llm.extension.agent import CallSite, complete_text
from tests.statement_ingestion import parse_and_load_statement_projection

_TEXT_PROMPT = "Extract this bank statement as strict JSON only (no prose, no markdown fence) with keys opening_balance, closing_balance, transactions (a list of {date, description, amount}). Amounts are negative for debits, positive for credits."
_TEXT_STATEMENT = "Opening balance: 100.00\n2026-01-02  Coffee shop        -5.00\n2026-01-05  Salary credit      +50.00\n2026-01-09  Groceries          -15.00\nClosing balance: 130.00\n"
_DUP_STATEMENT = "Opening balance: 1000.00\n2026-02-01  Deposit ABC        +250.00\n2026-02-01  Deposit ABC        +250.00\n2026-02-03  Service fee         -10.00\nClosing balance: 1490.00\n"
_VISION_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "vision"


def _loads_tolerant(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = (text.split("\n", 1)[1] if "\n" in text else text).rsplit("```", 1)[0]
    return json.loads(text)


# Recordings (#3153): `LLM_API_KEY=<key> pytest --record-mode=rewrite tests/extraction/test_extraction_cassette_replay.py`.
#
# A recording answers only the request body that it was recorded for, so a change of a statement prompt fails the
# replay until it is recorded again (#3149). The two failure-path tests run one pass: the loop of passes and its
# feedback have tests of their own, and a later pass reads page images, whose bytes depend on the renderer.


@pytest.mark.vcr
@pytest.mark.parametrize(
    ("statement", "expected_open", "expected_close", "dup_count"),
    [
        (_TEXT_STATEMENT, Decimal("100.00"), Decimal("130.00"), 0),
        (_DUP_STATEMENT, Decimal("1000.00"), Decimal("1490.00"), 2),
    ],
    ids=["plain", "duplicate-rows"],
)
async def test_AC23_6_extraction_text_happy_path_via_replay(
    vcr_llm, statement: str, expected_open: Decimal, expected_close: Decimal, dup_count: int
) -> None:
    data = _loads_tolerant(
        await complete_text(
            CallSite.EXTRACTION_STATEMENT,
            "multimodal",
            _TEXT_PROMPT + "\n\n" + statement,
            decoding=DecodingSpec(
                decoding_version="extraction.statement.v1",
                thinking=False,
                temperature=0.0,
                max_tokens=512,
                timeout=120.0,
            ),
            max_attempts=1,
        )
    )
    opening, closing = Decimal(str(data["opening_balance"])), Decimal(str(data["closing_balance"]))
    amounts = [Decimal(str(t["amount"])) for t in data["transactions"]]
    assert (
        len(amounts) == 3
        and abs(opening - expected_open) <= Decimal("0.01")
        and abs(closing - expected_close) <= Decimal("0.01")
        and abs(opening + sum(amounts, Decimal("0")) - closing) <= Decimal("0.01")
    )
    if dup_count:
        assert sum(1 for a in amounts if a == Decimal("250.00")) == dup_count


@pytest.mark.vcr
async def test_AC23_6_extraction_of_a_text_pdf_through_the_service_via_replay(vcr_llm) -> None:
    """The production request of the extraction service for a text PDF, answered by the recorded reply."""
    service = ExtractionService()
    res = await service.extract_financial_data(
        file_content=(_VISION_DIR / "simple_statement.pdf").read_bytes(),
        institution="ACME",
        file_type="pdf",
        filename="simple_statement.pdf",
    )
    bal = evaluate_statement_balance(
        opening=_safe_parse_decimal(res.get("opening_balance")),
        closing=_safe_parse_decimal(res.get("closing_balance")),
        currency=res.get("currency"),
        currency_balances=None,
        transactions=res["transactions"],
    )
    assert len(res["transactions"]) == 3 and bal["balance_valid"] is True


async def test_AC_llm_14_1_missing_period_remains_review_only_via_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "institution": "ACME",
        "account_last4": "5678",
        "currency": "SGD",
        "period_start": None,
        "period_end": None,
        "opening_balance": "1000.00",
        "closing_balance": "1720.00",
        "transactions": [
            {"date": "2026-03-02", "description": "Salary credit", "amount": "2000.00", "direction": "IN"},
            {"date": "2026-03-05", "description": "Rent payment", "amount": "1200.00", "direction": "OUT"},
            {"date": "2026-03-20", "description": "Groceries", "amount": "80.00", "direction": "OUT"},
        ],
    }
    service = ExtractionService()
    monkeypatch.setattr(service, "extract_financial_data", AsyncMock(return_value=payload))
    result = await service.parse_document(
        DocumentSource.resolve(path=Path("statement.pdf"), content=b"stub"),
        institution="ACME",
        user_id=uuid4(),
        file_type="pdf",
    )
    assert (
        result.balance_validated,
        result.period_start,
        result.period_end,
        result.missing_required_facts,
        result.review_reasons,
        len(result.transactions),
    ) == (True, None, None, ("period",), ("Source is missing required facts: statement period",), 3)


@pytest.mark.vcr
async def test_AC_llm_14_2_3_replay_failure_paths(db, test_user, monkeypatch: pytest.MonkeyPatch, vcr_llm) -> None:
    monkeypatch.setattr(settings, "ai_extract_max_attempts", 1)
    service = ExtractionService()
    no_dates_pdf = _VISION_DIR / "unhappy_no_dates_at_all.pdf"
    with pytest.raises(ExtractionError, match="Transaction missing required fields: date or amount"):
        await service.parse_document(
            DocumentSource.resolve(path=no_dates_pdf, content=no_dates_pdf.read_bytes()),
            institution="ACME",
            user_id=uuid4(),
            file_type="pdf",
        )

    unrec_pdf = _VISION_DIR / "unhappy_balance_unreconciled.pdf"
    result, summary, _ = await parse_and_load_statement_projection(
        service,
        db=db,
        source=DocumentSource.resolve(path=unrec_pdf, content=unrec_pdf.read_bytes()),
        institution="ACME",
        user_id=test_user.id,
        file_type="pdf",
    )
    persisted = (
        (await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id))).scalars().all()
    )
    assert (summary.status, result.balance_validated, persisted) == (BankStatementStatus.REJECTED, False, [])
