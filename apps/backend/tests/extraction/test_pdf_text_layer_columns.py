"""The text layer of a PDF keeps the amount columns of one document (#3112, #2987)."""

from __future__ import annotations

from io import BytesIO

import fitz
import pytest

from src.extraction.extension.pdf_text_layer import read_pdf_text_pages


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
