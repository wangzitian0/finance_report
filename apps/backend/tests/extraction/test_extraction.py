from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from reportlab.pdfgen import canvas

from src.extraction import DocumentSource
from src.extraction.base.validation import (
    _score_balance_progression,
    _score_currency_consistency,
    compute_confidence_score,
    validate_balance,
)
from src.extraction.extension.prompts.statement import get_parsing_prompt
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.observability import detect_pii

FIXTURES = {
    "DBS": {"success": True, "institution": "DBS", "statement": {"period_start": "2025-01-01", "period_end": "2025-01-31", "opening_balance": "100.00", "closing_balance": "250.00", "currency": "SGD", "balance_validated": True, "confidence_score": 95}, "events": [{"date": "2025-01-05", "description": "Card payment", "amount": "50.00", "direction": "OUT"}, {"date": "2025-01-10", "description": "Salary credit", "amount": "200.00", "direction": "IN"}]},
    "MariBank": {"success": True, "institution": "MariBank", "statement": {"period_start": "2025-04-01", "period_end": "2025-04-30", "opening_balance": "0.00", "closing_balance": "18.00", "currency": "SGD", "balance_validated": True}, "events": [{"date": "2025-04-03", "description": "Card payment", "amount": "12.00", "direction": "OUT"}, {"date": "2025-04-15", "description": "Transfer in", "amount": "30.00", "direction": "IN"}]},
    "GXS": {"success": True, "institution": "GXS", "statement": {"period_start": "2025-06-01", "period_end": "2025-06-30", "opening_balance": "0.00", "closing_balance": "0.25", "currency": "SGD", "balance_validated": True}, "events": [{"date": f"2025-06-{day:02d}", "description": "Interest", "amount": "0.01", "direction": "IN"} for day in range(1, 26)]},
}


def _extracted(txns: list[dict], *, institution: str = "DBS", currency: str | None = None, **extra) -> dict:
    base = {"institution": institution, "period_start": "2025-01-01", "period_end": "2025-01-31", "opening_balance": "0.00", "closing_balance": "100.00", "transactions": txns}
    if currency is not None:
        base["currency"] = currency
    return {**base, **extra}


@pytest.mark.parametrize(
    ("opening", "closing", "txns", "valid", "diff", "note_sub"),
    [
        ("1000.00", "1100.00", [{"amount": "200.00", "direction": "IN"}, {"amount": "100.00", "direction": "OUT"}], True, "0.00", None),
        ("1000.00", "2000.00", [{"amount": "100.00", "direction": "IN"}], False, None, "mismatch"),
        ("1000.00", "1100.005", [{"amount": "100.00", "direction": "IN"}], True, None, None),
    ],
)
def test_balance_validation(opening, closing, txns, valid, diff, note_sub):
    result = validate_balance({"opening_balance": opening, "closing_balance": closing, "transactions": txns})
    assert result["balance_valid"] is valid and (diff is None or result["difference"] == diff) and (note_sub is None or note_sub in result["notes"].lower())


@pytest.mark.parametrize(
    ("extracted", "validation", "low", "high"),
    [
        (_extracted([{"date": "2025-01-15", "amount": "100.00", "direction": "IN"}], opening_balance="1000.00", closing_balance="1100.00"), {"balance_valid": True, "difference": "0.00"}, 85, 100),
        (_extracted([{"date": "2025-01-15", "amount": "100.00", "direction": "IN"}], opening_balance="1000.00", closing_balance="1105.00"), {"balance_valid": False, "difference": "5.00"}, 60, 84),
        ({"institution": "DBS", "period_start": "invalid-date", "period_end": "2025-01-31", "opening_balance": "0", "closing_balance": "0", "transactions": []}, {"balance_valid": False, "difference": "100.00"}, 0, 59),
        ({"institution": "DBS", "period_start": "2025-01-01", "period_end": "2025-01-31", "opening_balance": "0", "closing_balance": "0"}, {"balance_valid": True, "difference": "0.00"}, 0, 100),
    ],
)
def test_confidence_bands(extracted, validation, low, high):
    assert low <= compute_confidence_score(extracted, validation) <= high


@pytest.mark.parametrize("name", list(FIXTURES))
def test_fixture_structure_and_invariants(name):
    fx = FIXTURES[name]
    assert fx["success"] is True and fx["institution"] == name and fx["events"] and all(len(e["date"]) == 10 and e["date"][4] == "-" for e in fx["events"])
    dbs = FIXTURES["DBS"]
    net = sum(Decimal(e["amount"]) if e["direction"] == "IN" else -Decimal(e["amount"]) for e in dbs["events"])
    assert abs(Decimal(dbs["statement"]["closing_balance"]) - (Decimal(dbs["statement"]["opening_balance"]) + net)) < Decimal("1.00")
    assert all(detect_pii(e["description"]) == [] for e in FIXTURES["MariBank"]["events"]) and sum(1 for e in FIXTURES["GXS"]["events"] if "Interest" in e["description"]) > 20


@pytest.mark.parametrize(
    ("institution", "required_groups"),
    [
        (None, [["financial statement parser"], ["JSON"], ["transactions"], ["MULTI-SECTION"], ["EVERY section"], ["COMPLETENESS SELF-CHECK"], ["reconcile EACH currency separately"], ["Never add amounts across different currencies"], ["EXACTLY ONCE"], ["do NOT double-count"], ["NEVER invent, fabricate"]]),
        ("DBS", [["DBS"], ["Singapore", "GIRO", "PayNow"]]),
        ("CMB", [["CMB", "招商"], ["Chinese", "中文"]]),
        ("UnknownBank", [["financial statement parser"]]),
        ("Futu", [["Futu", "富途"]]),
        ("GXS", [["GXS"]]),
        ("MariBank", [["MariBank"], ["Buy - Mari Invest"], ["Sell - Mari Invest"]]),
    ],
)
def test_get_parsing_prompt(institution, required_groups):
    prompt = get_parsing_prompt() if institution is None else get_parsing_prompt(institution)
    assert all(any((s in prompt.lower() if s == "financial statement parser" else s in prompt) for s in alts) for alts in required_groups)


@pytest.mark.parametrize(
    ("file_type", "mime", "data", "expected_type"),
    [
        ("pdf", "application/pdf", "https://s3.example.test/bucket/statement.pdf?signature=secret", "image_url"),
        ("pdf", "application/pdf", "data:application/pdf;base64,JVBERi0xLjQ=", "file"),
        ("png", "image/png", "data:image/png;base64,iVBORw0KGgo=", "image_url"),
        ("jpg", "image/jpeg", "data:image/jpeg;base64,/9j/4AAQSkZJRg==", "image_url"),
        ("jpeg", "image/jpeg", "https://example.com/statement.jpeg", "image_url"),
    ],
)
def test_media_payload_types(file_type, mime, data, expected_type):
    payload = ExtractionService()._build_media_payload(file_type, mime, data)
    assert payload["type"] == expected_type and (payload["file"] == {"filename": "statement.pdf", "file_data": data} if expected_type == "file" else payload["image_url"]["url"] == data)


async def test_pdf_render_institution_detection_and_service_helpers():
    service = ExtractionService()
    buf = BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.drawString(72, 720, "DBS statement fixture")
    pdf.save()
    batches = service._render_pdf_pages_as_image_payload_batches(buf.getvalue())
    assert len(batches) == len(batches[0]) == 1 and batches[0][0]["image_url"]["url"].startswith("data:image/png;base64,")

    with pytest.raises(ExtractionError, match="No valid file content or accessible URL"):
        service._build_ai_file_input(file_content=None, file_url="http://10.0.0.5/statements/file.pdf?token=secret", file_type="pdf", mime_type="application/pdf", prefer_url=True)
    with pytest.raises(ExtractionError, match="Institution is required for CSV"):
        await service.parse_document(DocumentSource.resolve(path=Path("test.csv"), content=b"date,amount\n2025-01-01,100"), institution=None, user_id=uuid4(), file_type="csv", account_id=None)
    with pytest.raises(Exception) as exc_info:
        await service.parse_document(DocumentSource.resolve(path=Path("test.pdf"), content=b"fake pdf content"), institution=None, user_id=uuid4(), file_type="pdf", account_id=None)
    assert "Institution is required" not in str(exc_info.value)
    with pytest.raises(ExtractionError, match="File content is required"):
        await service.parse_document(DocumentSource(path=Path("test.pdf"), content=None, url=None, content_hash="0" * 64, filename="test.pdf"), institution="DBS", user_id=uuid4(), file_type="pdf", account_id=None, force_model="google/gemini-2.0-flash-exp:free")

    d = service._safe_date("2025-01-01")
    assert ((d.year, d.month, d.day), service._safe_decimal("100.50", required=False), service._safe_decimal(None, required=False)) == ((2025, 1, 1), Decimal("100.50"), None)
    for fn, arg, match in [(service._safe_date, "invalid-date", "Invalid date format"), (service._safe_date, None, "Date is required"), (lambda v: service._safe_decimal(v, required=False), "abc", "Invalid decimal value"), (lambda v: service._safe_decimal(v, required=True), None, "Decimal value is required")]:
        with pytest.raises(ValueError, match=match):
            fn(arg)


@pytest.mark.parametrize(
    ("txns", "expected"),
    [
        ([{"balance_after": "1000.00", "amount": "100.00", "direction": "IN"}, {"balance_after": "1100.00", "amount": "100.00", "direction": "IN"}, {"balance_after": "1050.00", "amount": "50.00", "direction": "OUT"}], 10),
        ([{"balance_after": "1000.00", "amount": "100.00", "direction": "IN"}, {"balance_after": "5000.00", "amount": "100.00", "direction": "IN"}], 0),
        ([{"balance_after": "1000.00", "amount": "100.00", "direction": "IN"}], 0),
        ([{"amount": "100.00", "direction": "IN"}, {"amount": "200.00", "direction": "OUT"}], 0),
        ([], 0),
        ([{"balance_after": "1000.00", "amount": "100.00", "direction": "IN"}, {"balance_after": "1100.00", "amount": "100.00", "direction": "IN"}, {"balance_after": "9999.00", "amount": "50.00", "direction": "OUT"}], 5),
    ],
)
def test_progression(txns, expected):
    assert _score_balance_progression(txns) == expected


@pytest.mark.parametrize(
    ("txns", "header", "expected"),
    [
        ([{"currency": "SGD"}, {"currency": "SGD"}, {"currency": "SGD"}], "SGD", 5),
        ([{"currency": "USD"}, {"currency": "EUR"}], "SGD", 0),
        ([{"currency": "SGD"}, {"currency": "SGD"}, {"currency": "USD"}], None, 3),
        ([{"amount": "100"}, {"amount": "200"}], "SGD", 0),
        ([], "SGD", 0),
        ([{"currency": "SGD"}, {"currency": "USD"}, {"currency": "SGD"}, {"currency": "SGD"}], "SGD", 3),
        ([{"currency": "SGD"}, {"amount": "100"}, {"amount": "200"}], "SGD", 1),
    ],
)
def test_consistency(txns, header, expected):
    assert _score_currency_consistency(txns, header) == expected


@pytest.mark.parametrize(
    ("txns", "opening", "closing", "currency", "expected"),
    [
        ([{"date": "2025-01-01", "description": "A", "amount": "100.00", "direction": "IN", "currency": "SGD", "balance_after": "1000.00"}, {"date": "2025-01-02", "description": "B", "amount": "50.00", "direction": "IN", "currency": "SGD", "balance_after": "1050.00"}], "900.00", "1050.00", "SGD", 100),
        ([{"date": "2025-01-01", "description": "A", "amount": "100.00", "direction": "IN"}], "0.00", "100.00", None, 85),
    ],
)
def test_v2_scoring(txns, opening, closing, currency, expected):
    assert compute_confidence_score(_extracted(txns, opening_balance=opening, closing_balance=closing, currency=currency), {"balance_valid": True, "difference": "0.00"}) == expected


def test_brokerage_and_effective_count_penalty():
    bal = {"balance_valid": True, "difference": "0.00"}
    one_broker = _extracted([{"date": "2025-06-15", "description": "Aggregate", "amount": "100.00", "direction": "IN", "currency": "HKD"}], institution="Futu", currency="HKD", period_start="2025-06-01", period_end="2025-06-30")
    two_broker = _extracted([{"date": "2025-06-10", "description": "Buy", "amount": "40.00", "direction": "OUT", "currency": "HKD"}, {"date": "2025-06-20", "description": "Sell", "amount": "140.00", "direction": "IN", "currency": "HKD"}], institution="Futu", currency="HKD", period_start="2025-06-01", period_end="2025-06-30")
    unpenalized, penalized = compute_confidence_score(one_broker, bal, is_brokerage=False), compute_confidence_score(one_broker, bal, is_brokerage=True)
    not_capped, capped = compute_confidence_score(two_broker, bal, is_brokerage=True), compute_confidence_score(two_broker, bal, is_brokerage=True, effective_txn_count=1)
    assert penalized <= 60 < unpenalized and compute_confidence_score(one_broker, bal) == unpenalized and capped <= 60 < not_capped
    assert compute_confidence_score(_extracted([{"date": "2025-01-01", "description": "A", "amount": "100.00", "direction": "IN"}]), bal, is_brokerage=False) == 85
