"""Row amounts and balances checked against the PDF text layer (#2987)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import fitz
import pytest
import structlog

from src.extraction import DocumentSource
from src.extraction.base.source_balance_check import rows_missing_from_text
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
