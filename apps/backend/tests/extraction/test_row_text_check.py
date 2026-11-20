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
from src.extraction.extension.service import ExtractionService, rows_not_in_text_review_reason

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


def _statement_pdf(*, balance_column: bool = True, rows: bool = True) -> bytes:
    lines = [
        "Row Check Bank",
        "Account 5551-234-7702",
        "Statement period 2026-05-01 to 2026-05-31",
        "Opening Balance 2000.00",
        *(f"{d} {desc} {amt} {bal if balance_column else ''}" for d, desc, amt, _, bal in (ROWS if rows else [])),
        "Closing Balance 4837.50",
    ]
    doc = fitz.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 72 + 16 * i), line)
    data = doc.tobytes()
    doc.close()
    return data


async def _parse(tmp_path, payload: dict, **pdf_options):
    svc = ExtractionService()
    content = _statement_pdf(**pdf_options)
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
    text = (
        "Opening 2,000.00\nSalary 3,000.00 5 000,00\nInterest 1.5 (5001.50)\nGrocery 85.40 4916.10\n"
        "A 12.00 4904.10\nB 7.00 4897.10\nC 9.00 4888.10"
    )
    rows = [
        (Decimal("3000.00"), Decimal("5000.00")),
        (Decimal("1.50"), Decimal("-5001.50")),
        (Decimal("85.90"), Decimal("4916.10")),
        (Decimal("85.40"), Decimal("4916.99")),
        (Decimal("85.40"), None),
        (Decimal("0.00"), Decimal("0")),
        (Decimal("12.00"), Decimal("4904.10")),
        (Decimal("7.00"), Decimal("4897.10")),
        (Decimal("9.00"), Decimal("4888.10")),
    ]
    assert rows_missing_from_text(text, rows) == [3, 4]
    assert rows_missing_from_text(text, rows[:2]) == []
    zero_rows = [(Decimal("0.00"), Decimal("100.00")), (Decimal("0"), None)]
    assert rows_missing_from_text("Fee 12.50 balance 100.00", zero_rows) == []
    assert rows_missing_from_text("", rows) is None
    assert rows_missing_from_text("page 1 of 2", rows) is None


@pytest.mark.no_db
def test_rows_missing_from_text_says_nothing_when_the_text_does_not_cover_the_rows():
    """AC-extraction.2987.4: a text that prints fewer than 4 of 5 row amounts is unusable, not 100 misread rows."""
    rows = [(Decimal(f"{n}0.50"), None) for n in range(1, 11)]
    cover_page = "Opening 2000.00 Closing 4837.50 10.50 20.50"
    assert rows_missing_from_text(cover_page, rows) is None
    four_fifths = " ".join(f"{n}0.50" for n in range(1, 9))
    assert rows_missing_from_text(four_fifths, rows) == [9, 10]


@pytest.mark.no_db
def test_rows_missing_from_text_checks_balances_only_when_the_text_prints_a_balance_column():
    """AC-extraction.2987.4: a credit card prints no balance column, and the model may compute balance_after."""
    amounts_only = "Grocery 85.40 Phone 23.60 Coffee 55.00 Salary 3000.00 Interest 1.50"
    computed = [
        (Decimal("85.40"), Decimal("4916.10")),
        (Decimal("23.60"), Decimal("4892.50")),
        (Decimal("55.00"), Decimal("4837.50")),
        (Decimal("3000.00"), Decimal("7837.50")),
        (Decimal("1.50"), Decimal("7839.00")),
    ]
    assert rows_missing_from_text(amounts_only, computed) == []
    assert rows_missing_from_text(amounts_only, [(Decimal("85.41"), Decimal("4916.10")), *computed[1:]]) == [1]
    with_column = amounts_only + " 4916.10 4892.50 4837.50 7837.50 7839.00"
    assert rows_missing_from_text(with_column, [(a, b + 1 if a == Decimal("55.00") else b) for a, b in computed]) == [3]


@pytest.mark.no_db
def test_rows_not_in_text_review_reason_names_at_most_20_rows():
    """The review reason names at most 20 row numbers; the log line holds all of them."""
    assert rows_not_in_text_review_reason([3, 7, 9]) == "Rows not found in the document text: 3, 7, 9"
    named = ", ".join(str(n) for n in range(1, 21))
    assert rows_not_in_text_review_reason(list(range(1, 21))) == f"Rows not found in the document text: {named}"
    assert rows_not_in_text_review_reason(list(range(1, 22))).endswith("20 and 1 more")
    assert (
        rows_not_in_text_review_reason(list(range(1, 26))) == f"Rows not found in the document text: {named} and 5 more"
    )


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


async def test_AC_extraction_2987_4_a_statement_without_a_balance_column_is_not_flagged_for_computed_balances(tmp_path):
    """AC-extraction.2987.4: the balances that the model computed for a credit card do not send its rows to review."""
    parsed = await _parse(tmp_path, _payload(), balance_column=False)
    assert parsed.review_reasons == () and parsed.confidence >= Decimal("0.85") and len(parsed.transactions) == 5


async def test_AC_extraction_2987_4_a_text_layer_without_the_rows_does_not_name_100_misread_rows(tmp_path):
    """AC-extraction.2987.4: a text layer that prints no row is a text layer problem; no row number is named."""
    parsed = await _parse(tmp_path, _payload(), rows=False)
    assert not any("Rows not found" in reason for reason in parsed.review_reasons)


async def test_AC_extraction_2987_6_a_direction_that_the_balance_contradicts_is_repaired_and_logged(tmp_path):
    """AC-extraction.2987.6: the row takes the direction of the balance step, and one log line counts the conflict."""
    with structlog.testing.capture_logs() as clean_logs:
        clean = await _parse(tmp_path, _payload())
    assert [e for e in clean_logs if e["event"] == "statement.extraction.directions_repaired"] == []

    with structlog.testing.capture_logs() as logs:
        repaired = await _parse(tmp_path, _payload(row2={"direction": "IN"}))
    assert [str(t.direction).rsplit(".", 1)[-1].upper() for t in repaired.transactions] == [
        str(t.direction).rsplit(".", 1)[-1].upper() for t in clean.transactions
    ]
    assert str(repaired.transactions[2].direction).rsplit(".", 1)[-1].upper() == "OUT"
    entries = [e for e in logs if e["event"] == "statement.extraction.directions_repaired"]
    assert entries == [
        {
            "event": "statement.extraction.directions_repaired",
            "log_level": "warning",
            "row_count": 5,
            "repaired_count": 1,
        }
    ]
