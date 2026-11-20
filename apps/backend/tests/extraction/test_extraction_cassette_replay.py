from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.config import settings
from src.extraction import BankStatementStatus, DocumentSource
from src.extraction.base.validation import _safe_parse_decimal, evaluate_statement_balance
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.extraction.orm.layer2 import AtomicTransaction
from src.llm import accumulate_stream, stream_ai_json
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


def _stub_env_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_api_key", "sk-test-replay-dummy", raising=False)
    monkeypatch.setattr(settings, "ai_provider", "openai-compatible-test", raising=False)


async def test_AC23_6_extraction_text_happy_path_via_replay() -> None:
    for stmt, expected_open, expected_close, dup_count in [
        (_TEXT_STATEMENT, Decimal("100.00"), Decimal("130.00"), 0),
        (_DUP_STATEMENT, Decimal("1000.00"), Decimal("1490.00"), 2),
    ]:
        data = _loads_tolerant(
            await accumulate_stream(
                stream_ai_json(
                    messages=[{"role": "user", "content": _TEXT_PROMPT + "\n\n" + stmt}],
                    model="glm-5.2",
                    max_tokens=512,
                    temperature=0.0,
                    thinking={"type": "disabled"},
                )
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

    service = ExtractionService()
    service.api_key = service.api_key or "replay"
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


async def test_AC_llm_14_2_3_replay_failure_paths(db, test_user, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_env_provider(monkeypatch)
    service = ExtractionService()
    service.api_key = service.api_key or "replay"
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


async def test_AC_extraction_3112_prompt_takes_printed_numbers_and_the_amount_column_via_replay() -> None:
    """#3112: two amount columns, no printed opening balance, one row without a printed balance.

    The descriptions of rows 1 and 2 name the other direction, as the ICICI sample does. The recorded reply
    shows that the model follows prompt rules 4, 9 and 12.
    """
    service = ExtractionService()
    service.api_key = service.api_key or "replay"
    res = await service.extract_financial_data(
        file_content=(_VISION_DIR / "dual_columns_no_opening.pdf").read_bytes(),
        institution="ACME",
        file_type="pdf",
        filename="dual_columns_no_opening.pdf",
    )
    rows = res["transactions"]
    assert [(row["direction"], _safe_parse_decimal(row["amount"])) for row in rows] == [
        ("OUT", Decimal("1935.30")),
        ("IN", Decimal("500.00")),
        ("OUT", Decimal("164.58")),
        ("OUT", Decimal("25.00")),
        ("IN", Decimal("10.00")),
    ]
    assert [_safe_parse_decimal(row.get("balance_after")) for row in rows] == [
        Decimal("6864.58"),
        Decimal("7364.58"),
        Decimal("7200.00"),
        None,
        Decimal("7185.00"),
    ]
    assert _safe_parse_decimal(res.get("opening_balance")) is None
    assert _safe_parse_decimal(res.get("closing_balance")) == Decimal("7185.00")
