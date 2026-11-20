"""Row amounts checked against the PDF text, document-level column layout, and account split (#2987, #3112, #2983)."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import fitz
import pytest
import structlog

from src.extraction import DocumentSource
from src.extraction.base.paged_extraction import split_paged_extractions_by_account
from src.extraction.base.source_balance_check import rows_missing_from_text
from src.extraction.extension.pdf_text_layer import read_pdf_text_pages
from src.extraction.extension.prompts.statement import SYSTEM_PROMPT
from src.extraction.extension.service import ExtractionService

ROWS = [
    ("2026-05-02", "Salary Acme Pte Ltd", "3000.00", "IN", "5000.00"),
    ("2026-05-03", "Interest", "1.50", "IN", "5001.50"),
    ("2026-05-10", "Grocery Market", "85.40", "OUT", "4916.10"),
    ("2026-05-12", "Phone Plan", "23.60", "OUT", "4892.50"),
    ("2026-05-20", "Coffee House", "55.00", "OUT", "4837.50"),
]


def _payload(**row_changes: dict) -> dict:
    rows = [
        {"date": d, "description": desc, "amount": amt, "direction": dir_, "balance_after": bal}
        for d, desc, amt, dir_, bal in ROWS
    ]
    for index, change in row_changes.items():
        rows[int(index.removeprefix("row"))].update(change)
    return {
        "institution": "Row Check Bank",
        "account_last4": "7702",
        "currency": "SGD",
        "period_start": "2026-05-01",
        "period_end": "2026-05-31",
        "opening_balance": "2000.00",
        "closing_balance": "4837.50",
        "transactions": rows,
    }


def _statement_pdf() -> bytes:
    lines = [
        "Row Check Bank",
        "Account 5551-234-7702",
        "Statement period 2026-05-01 to 2026-05-31",
        "Opening Balance 2000.00",
        *(f"{d} {desc} {amt} {bal}" for d, desc, amt, _, bal in ROWS),
        "Closing Balance 4837.50",
    ]
    doc = fitz.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 72 + 16 * i), line)
    data = doc.tobytes()
    doc.close()
    return data


async def _parse(tmp_path, payload: dict):
    svc = ExtractionService()
    content = _statement_pdf()
    path = tmp_path / "statement.pdf"
    path.write_bytes(content)
    with patch.object(svc, "extract_financial_data", new=AsyncMock(return_value=payload)):
        return await svc.parse_document(
            DocumentSource.resolve(path=path, content=content),
            institution="Row Check Bank",
            user_id=uuid4(),
            file_type="pdf",
        )


@pytest.mark.no_db
def test_rows_missing_from_text_names_each_row_by_number():
    """AC-extraction.2987.4: a row whose amount or balance is not printed is named by its 1-based row number."""
    text = "Opening 2,000.00\nSalary 3,000.00 5 000,00\nInterest 1.5 (5001.50)\nGrocery 85.40 4916.10"
    rows = [
        (Decimal("3000.00"), Decimal("5000.00")),
        (Decimal("1.50"), Decimal("-5001.50")),
        (Decimal("85.90"), Decimal("4916.10")),
        (Decimal("85.40"), Decimal("4916.99")),
        (Decimal("85.40"), None),
        (Decimal("0.00"), Decimal("0")),
    ]
    assert rows_missing_from_text(text, rows) == [3, 4]
    assert rows_missing_from_text(text, rows[:2]) == []
    assert rows_missing_from_text("", rows) is None
    assert rows_missing_from_text("page 1 of 2", rows) is None


async def test_AC_extraction_2987_4_misread_row_goes_to_review_and_is_not_rejected(tmp_path):
    """AC-extraction.2987.4: one misread balance_after names row 3 in the review reason; the rows are kept."""
    clean = await _parse(tmp_path, _payload())
    assert clean.review_reasons == () and clean.confidence >= Decimal("0.85")

    with structlog.testing.capture_logs() as logs:
        flagged = await _parse(tmp_path, _payload(row2={"balance_after": "4916.70"}))
    assert flagged.review_reasons == ("Rows not found in the document text: 3",)
    assert flagged.balance_validated is True and len(flagged.transactions) == 5
    assert flagged.confidence < Decimal("0.85")
    entry = next(e for e in logs if e["event"] == "statement.extraction.rows_not_in_text")
    assert entry["row_count"] == 5 and entry["missing_count"] == 1 and entry["rows"] == [3]
    assert all(amount not in str(entry) for amount in ("4916.70", "85.40", "Grocery"))


async def test_AC_extraction_2987_4_misread_amount_is_named_when_the_balance_gate_rejects(tmp_path):
    """AC-extraction.2987.4: a misread amount that breaks the balance names its row in the rejection message."""
    rejected = await _parse(tmp_path, _payload(row3={"amount": "28.60"}))
    assert rejected.transactions == () and rejected.balance_validated is False
    assert rejected.review_reasons[0].endswith("Rows not found in the document text: 4")


def _table_pdf(debit_header: str, credit_header: str, *, header_on_page_two: bool = False) -> bytes:
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    pdf = canvas.Canvas(buf)

    def header() -> None:
        pdf.drawString(50, 720, "Date")
        pdf.drawString(120, 720, "Description")
        pdf.drawString(280, 720, debit_header)
        pdf.drawString(380, 720, credit_header)
        pdf.drawString(480, 720, "Balance")

    def rows(first: str, second: str) -> None:
        pdf.drawString(50, 700, "01/07")
        pdf.drawString(120, 700, first)
        pdf.drawString(280, 700, "10.00")
        pdf.drawString(480, 700, "990.00")
        pdf.drawString(50, 680, "02/07")
        pdf.drawString(120, 680, second)
        pdf.drawString(380, 680, "100.00")
        pdf.drawString(480, 680, "1090.00")

    header()
    rows("COFFEE SHOP", "PAYROLL")
    pdf.showPage()
    if header_on_page_two:
        header()
    rows("BOOK STORE", "REFUND")
    pdf.save()
    return buf.getvalue()


def _amount_offsets(header_page: str, debit_header: str, credit_header: str, page: str, rows: tuple[str, str]):
    """Return how many characters the debit and the credit amount start away from their headers."""
    header = next(line for line in header_page.splitlines() if debit_header in line and credit_header in line)
    lines = page.splitlines()
    debit_line = next(line for line in lines if rows[0] in line)
    credit_line = next(line for line in lines if rows[1] in line)
    return (
        abs(debit_line.index("10.00") - header.index(debit_header)),
        abs(credit_line.index("100.00") - header.index(credit_header)),
    )


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("debit_header", "credit_header"),
    [
        ("Débit", "Crédit"),
        ("Paid out", "Paid in"),
        ("Money out", "Money in"),
        ("Dr", "Cr"),
        ("Dr.", "Cr."),
        ("Debit Amt", "Credit Amt"),
    ],
)
def test_AC_extraction_3112_dual_amount_headers_keep_the_columns(debit_header, credit_header):
    """AC-extraction.3112.1: under each dual header pair an amount starts at most 2 characters from its header."""
    pages = read_pdf_text_pages(_table_pdf(debit_header, credit_header, header_on_page_two=True))
    assert pages is not None and len(pages) == 2
    offsets = _amount_offsets(pages[0], debit_header, credit_header, pages[0], ("COFFEE SHOP", "PAYROLL"))
    assert max(offsets) <= 2, offsets


@pytest.mark.no_db
def test_AC_extraction_3112_later_pages_keep_the_column_layout_of_the_header_page():
    """AC-extraction.3112.2: a page without headers keeps the column positions of the earlier header page."""
    pages = read_pdf_text_pages(_table_pdf("Debit", "Credit"))
    assert pages is not None and len(pages) == 2
    offsets = _amount_offsets(pages[0], "Debit", "Credit", pages[1], ("BOOK STORE", "REFUND"))
    assert max(offsets) <= 2, offsets


@pytest.mark.no_db
def test_single_amount_column_pdf_keeps_the_flat_text():
    """A document without dual amount headers keeps the sorted flat text on every page."""
    content = _table_pdf("Amount", "Notes")
    document = fitz.open(stream=content, filetype="pdf")
    flat = [page.get_text(sort=True) for page in document]
    document.close()
    assert read_pdf_text_pages(content) == flat
    assert max(_amount_offsets(flat[0], "Amount", "Notes", flat[0], ("COFFEE SHOP", "PAYROLL"))) > 2


@pytest.mark.no_db
def test_AC_extraction_3112_base_prompt_has_no_self_check_and_keeps_unprinted_balances_null():
    """AC-extraction.3112.3: the base prompt asks for no model-side reconciliation and for null unprinted balances."""
    assert "SELF-CHECK" not in SYSTEM_PROMPT and "MUST equal" not in SYSTEM_PROMPT
    assert "ONLY when the document explicitly prints it; otherwise null" in SYSTEM_PROMPT


META = {
    "institution": "Two Account Bank",
    "account_last4": "1111",
    "currency": "EUR",
    "period_start": "2026-05-01",
    "period_end": "2026-05-31",
    "opening_balance": "100.00",
    "closing_balance": "403.12",
}
FIRST_ACCOUNT = {
    "account_last4": "1111",
    "opening_balance": "100.00",
    "closing_balance": "238.52",
    "transactions": [{"description": "a1", "amount": "138.52", "direction": "IN"}],
}
SECOND_ACCOUNT = {
    "account_last4": "2222",
    "opening_balance": "200.00",
    "closing_balance": "403.12",
    "transactions": [{"description": "b1", "amount": "203.12", "direction": "IN"}],
}


@pytest.mark.no_db
def test_AC_extraction_2983_7_each_account_keeps_its_own_closing_balance():
    """AC-extraction.2983.7: a metadata part with an account suffix gives no balance to any account."""
    continuation = {"transactions": [{"description": "b2", "amount": "1.00", "direction": "OUT"}]}
    accounts = split_paged_extractions_by_account([FIRST_ACCOUNT, SECOND_ACCOUNT, continuation], metadata=META)
    assert [
        (a["account_last4"], a["opening_balance"], a["closing_balance"], [t["description"] for t in a["transactions"]])
        for a in accounts
    ] == [("1111", "100.00", "238.52", ["a1"]), ("2222", "200.00", "403.12", ["b1", "b2"])]
    assert all(
        (a["institution"], a["period_start"], a["period_end"]) == ("Two Account Bank", "2026-05-01", "2026-05-31")
        for a in accounts
    )

    no_printed_balance = {k: v for k, v in FIRST_ACCOUNT.items() if k not in ("opening_balance", "closing_balance")}
    first, _second = split_paged_extractions_by_account([no_printed_balance, SECOND_ACCOUNT], metadata=META)
    assert first.get("opening_balance") is None and first.get("closing_balance") is None

    leading = {"transactions": [{"description": "a0", "amount": "2.00", "direction": "IN"}]}
    first, _second = split_paged_extractions_by_account([leading, FIRST_ACCOUNT, SECOND_ACCOUNT], metadata=META)
    assert [t["description"] for t in first["transactions"]] == ["a0", "a1"]


@pytest.mark.no_db
def test_AC_extraction_2983_8_metadata_suffix_alone_is_not_an_account():
    """AC-extraction.2983.8: row parts of one account give one account, without the balances of the metadata part."""
    rows_only = {k: v for k, v in SECOND_ACCOUNT.items() if k not in ("opening_balance", "closing_balance")}
    accounts = split_paged_extractions_by_account([rows_only], metadata=META)
    assert len(accounts) == 1
    only = accounts[0]
    assert only["account_last4"] == "2222" and only["institution"] == "Two Account Bank"
    assert only.get("opening_balance") is None and only.get("closing_balance") is None
    assert [t["description"] for t in only["transactions"]] == ["b1"]


def _image_batches(*_args, **_kwargs):
    return [[{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]]


@pytest.mark.no_db
async def test_AC_extraction_2983_9_single_batch_account_conflict_is_split_in_the_first_pass():
    """AC-extraction.2983.9: a metadata reply and a rows reply with two suffixes end in pass 1, without a third call."""
    service = ExtractionService()
    service.api_key, service.multimodal_model = "test-key", "test-model"
    model_call = AsyncMock(side_effect=[dict(META), dict(SECOND_ACCOUNT)])
    with (
        patch.object(service, "_extract_json_with_model", model_call),
        patch.object(service, "_build_vision_media_payload_batches", _image_batches),
    ):
        slices, split_meta_agreed = await service._extract_with_balance_retry(
            file_content=b"png", institution=None, file_type="png", file_url=None, force_model=None, filename="s.png"
        )
    assert model_call.await_count == 2
    assert split_meta_agreed is False and len(slices) == 1
    payload = slices[0].payload
    assert payload["account_last4"] == "2222" and payload["institution"] == "Two Account Bank"
    assert payload.get("opening_balance") is None and payload.get("closing_balance") is None
    assert [t["description"] for t in payload["transactions"]] == ["b1"]


def _text_pdf(page_count: int) -> bytes:
    doc = fitz.open()
    for index in range(page_count):
        doc.new_page().insert_text((72, 72), f"{index + 1} Jan PAYMENT {index + 1}0.00 CR")
    data = doc.tobytes()
    doc.close()
    return data


@pytest.mark.no_db
async def test_AC_extraction_2983_10_text_split_by_account_does_not_fall_back_to_images():
    """AC-extraction.2983.10: an account split read from the text layer is the result; no image call follows."""
    service = ExtractionService()
    service.api_key, service.multimodal_model = "test-key", "test-model"
    model_call = AsyncMock(side_effect=[dict(META), dict(FIRST_ACCOUNT), dict(SECOND_ACCOUNT)])
    images = AsyncMock(side_effect=AssertionError("the image path must not run"))
    with (
        patch.object(service, "_extract_json_with_model", model_call),
        patch.object(service, "_build_vision_media_payload_batches", images),
    ):
        extracted = await service.extract_financial_data(_text_pdf(service.PDF_VISION_MAX_PAGES + 2), None, "pdf")
    assert model_call.await_count == 3
    assert [(a["account_last4"], a["closing_balance"]) for a in extracted["accounts"]] == [
        ("1111", "238.52"),
        ("2222", "403.12"),
    ]
