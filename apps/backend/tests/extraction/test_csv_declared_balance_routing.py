from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic_ai.exceptions import ModelHTTPError

from src.config import settings
from src.extraction.base.result import StatementExtractionResult
from src.extraction.base.reviewed_statement_envelope import supports_reviewed_statement_envelope
from src.extraction.base.types import DocumentSource
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.llm import ModelCallFailed, ModelFailureKind
from tests._support.fake_llm import install_fake_model

DECLARED_HEADER = "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount"
RECONCILED = f"{DECLARED_HEADER}\nSGD,2025-01-01,2025-01-31,100.00,125.00,2025-01-15,Interest,25.00\n"
UNRECONCILED = f"{DECLARED_HEADER}\nSGD,2025-01-01,2025-01-31,100.00,999.00,2025-01-15,Interest,25.00\n"
JOURNEY_UPLOAD = "Statement Currency,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount\nSGD,20000.00,99999.00,2026-02-10,Unverified Expense,-500.00\n"
NO_BALANCES = "Date,Description,Amount\n2025-01-15,Interest,25.00\n"


async def _parse(text: str) -> StatementExtractionResult:
    return await ExtractionService().parse_document(
        DocumentSource.resolve(path=Path("/tmp/declared.csv"), content=text.encode(), filename="declared.csv"),
        "Example Bank",
        user_id=uuid4(),
        file_type="csv",
        account_id=uuid4(),
        db=None,
    )


@pytest.mark.parametrize("text", [UNRECONCILED, JOURNEY_UPLOAD], ids=["opening-100-closing-999", "journey-upload"])
async def test_AC_extraction_2504_1_an_unreconciled_declared_csv_stays_reviewable(text: str) -> None:
    result = await _parse(text)
    assert len(result.transactions) == 1 and result.balance_validated is False and result.confidence < Decimal("0.5")
    assert not any("llm_led" in r or "Retry parsing" in r for r in result.review_reasons)


async def test_AC_extraction_2504_1_and_2822_1_csv_balance_and_confidence() -> None:
    r_unrec, r_rec, r_none = await _parse(UNRECONCILED), await _parse(RECONCILED), await _parse(NO_BALANCES)
    assert (
        r_unrec.review_reasons,
        len(r_rec.transactions),
        r_rec.balance_validated,
        r_rec.confidence,
        len(r_none.transactions),
        r_none.balance_validated,
        r_none.confidence <= Decimal("0.59"),
    ) == (("Balance mismatch: expected 125.00, got 999.00",), 1, True, Decimal("0.91"), 1, None, True)
    rich = await _parse(
        "Date,Description,Amount,Currency,Reference,Balance,Statement Opening Balance,Statement Closing Balance,Statement Period Start,Statement Period End\n"
        "2026-10-05,ACME Corp Salary,8500.00,SGD,SAL-2026-10,18500.00,10000.00,14180.00,2026-10-01,2026-10-31\n"
        "2026-10-10,Marina Bay Condo Rent,-3200.00,SGD,RENT-2026-10,15300.00,10000.00,14180.00,2026-10-01,2026-10-31\n"
        "2026-10-15,NTUC FairPrice Groceries,-320.00,SGD,POS-2026-1015,14980.00,10000.00,14180.00,2026-10-01,2026-10-31\n"
        "2026-10-20,Credit Card Bill Payment,-800.00,SGD,CC-2026-1020,14180.00,10000.00,14180.00,2026-10-01,2026-10-31\n"
    )
    assert (
        len(rich.transactions),
        rich.balance_validated,
        all(t.currency == "SGD" for t in rich.transactions),
        [t.balance_after for t in rich.transactions],
        rich.confidence >= Decimal("0.85"),
        rich.missing_required_facts,
        supports_reviewed_statement_envelope(rich),
    ) == (
        4,
        True,
        True,
        [Decimal("18500.00"), Decimal("15300.00"), Decimal("14980.00"), Decimal("14180.00")],
        True,
        (),
        False,
    )


async def test_ai_csv_parsing_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = ExtractionService()
    ai_map = '{"date": "Txn Date", "description": "Narration", "amount": null, "debit": "Debit", "credit": "Credit", "balance": "Balance", "reference": null, "currency": null, "date_format": "%d/%m/%Y", "has_header": true, "institution_guess": "Unknown Bank"}'
    csv1 = b"Txn Date,Narration,Debit,Credit,Balance\n15/01/2025,Coffee Shop,25.00,,975.00\n16/01/2025,Salary,,3000.00,3975.00\n"
    install_fake_model(monkeypatch, ai_map)
    with (
        patch.object(svc, "api_key", "test-key"),
        patch.object(svc, "small_model", "test-model"),
    ):
        res1 = await svc._parse_csv_content(csv1, "UnknownBank")
    assert (
        len(res1["transactions"]),
        res1["transactions"][0]["direction"],
        res1["transactions"][0]["amount"],
        res1["transactions"][0]["description"],
        res1["transactions"][1]["direction"],
        res1["transactions"][1]["amount"],
    ) == (2, "OUT", "25.00", "Coffee Shop", "IN", "3000.00")

    amt_rows = [
        {"Txn Date": "bad-date", "Narration": "Bad Date", "Amount": "10.00"},
        {"Txn Date": "15/01/2025", "Narration": "Bad Amount", "Amount": "not-money"},
        {"Txn Date": "16/01/2025", "Narration": "Empty Amount", "Amount": ""},
        {"Txn Date": "17/01/2025", "Narration": "Refund", "Amount": "-4.50"},
    ]
    install_fake_model(
        monkeypatch,
        '{"date": "Txn Date", "description": "Narration", "amount": "Amount", "debit": null, "credit": null}',
    )
    with (
        patch.object(svc, "api_key", "test-key"),
        patch.object(svc, "small_model", "test-model"),
    ):
        t1, ps, pe = await svc._ai_parse_csv(
            headers=["Txn Date", "Narration", "Amount"],
            rows=amt_rows,
            institution="UnknownBank",
            parse_date=lambda v: datetime.strptime(v, "%d/%m/%Y").date() if "/" in v else None,
            parse_amount=lambda v: Decimal(v) if v not in {"", "not-money"} else None,
        )
    assert (len(t1), t1[0]["direction"], t1[0]["amount"], ps == pe) == (1, "OUT", "4.50", True)

    dc_rows = [
        {"Txn Date": "15/01/2025", "Narration": "No Amount", "Debit": "", "Credit": ""},
        {"Txn Date": "16/01/2025", "Narration": "Salary", "Debit": "", "Credit": "3000.00"},
    ]
    install_fake_model(
        monkeypatch,
        '{"date": "Txn Date", "description": "Narration", "amount": null, "debit": "Debit", "credit": "Credit"}',
    )
    with (
        patch.object(svc, "api_key", "test-key"),
        patch.object(svc, "small_model", "test-model"),
    ):
        t2, _, _ = await svc._ai_parse_csv(
            headers=["Txn Date", "Narration", "Debit", "Credit"],
            rows=dc_rows,
            institution="UnknownBank",
            parse_date=lambda v: datetime.strptime(v, "%d/%m/%Y").date(),
            parse_amount=lambda v: Decimal(v) if v else None,
        )
    res_dbs = await svc._parse_csv_content(
        b"Transaction Date,Transaction Ref1,Debit Amount,Credit Amount\n15 Jan 2025,Coffee Shop,25.00,\n16 Jan 2025,Salary,,3000.00\n",
        "DBS",
    )
    assert (
        len(t2),
        t2[0]["direction"],
        len(res_dbs["transactions"]),
        res_dbs["transactions"][0]["direction"],
        res_dbs["transactions"][1]["direction"],
    ) == (1, "IN", 2, "OUT", "IN")

    def provider_down(_prompt: str) -> str:
        raise ModelHTTPError(503, "test-small-model", {"error": "provider down"})

    # A failed model call names the model as the cause: it is not the error of a model that found no rows.
    install_fake_model(monkeypatch, provider_down)
    with (
        patch.object(svc, "api_key", "test-key"),
        patch.object(svc, "small_model", "test-model"),
        pytest.raises(ExtractionError, match=r"^AI column mapping unavailable \(unavailable\)$") as failed,
    ):
        await svc._parse_csv_content(b"Col1,Col2,Col3\nfoo,bar,baz\n", "UnknownFormat")
    assert isinstance(failed.value.__cause__, ModelCallFailed) and failed.value.__cause__.kind is ModelFailureKind.UNAVAILABLE

    # A model that answers with a mapping that matches no row is not a failed call.
    install_fake_model(monkeypatch, '{"date": "Col1", "description": "Col2", "amount": "Col3"}')
    with (
        patch.object(svc, "api_key", "test-key"),
        patch.object(svc, "small_model", "test-model"),
        pytest.raises(ExtractionError, match="No valid transactions found"),
    ):
        await svc._parse_csv_content(b"Col1,Col2,Col3\nfoo,bar,baz\n", "UnknownFormat")


async def test_csv_with_no_ai_configured_keeps_the_generic_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """No key means no AI fallback: the failure is `not_configured`, and the file has no rows that the heuristics read."""
    monkeypatch.setattr(settings, "ai_api_key", "")
    with pytest.raises(ExtractionError, match="No valid transactions found"):
        await ExtractionService()._parse_csv_content(b"Col1,Col2,Col3\nfoo,bar,baz\n", "UnknownFormat")


async def test_e2e_hard_gate_csv_fixture_requires_reviewed_statement_envelope() -> None:
    """Guard E2E fixture contract: missing period/balances triggers envelope hard gate."""
    fixture_path = (
        Path(__file__).resolve().parents[4] / "tests" / "e2e" / "fixtures" / "csv_envelope_hard_gate_statement.csv"
    )
    raw = fixture_path.read_bytes()
    result = await ExtractionService().parse_document(
        DocumentSource.resolve(path=fixture_path, content=raw, filename=fixture_path.name),
        "Generic Vision Hard Gate",
        user_id=uuid4(),
        file_type="csv",
        account_id=None,
        db=None,
    )
    assert len(result.transactions) == 6
    assert result.missing_required_facts == ("period", "balances")
    assert supports_reviewed_statement_envelope(result) is True
