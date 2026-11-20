"""The text layer of a PDF keeps the amount columns of one document (#3112, #2987)."""

from __future__ import annotations

from io import BytesIO

import fitz
import pytest

from src.extraction.extension.pdf_text_layer import read_pdf_text_pages


def _table_pdf(
    debit_header: str,
    credit_header: str,
    *,
    header_on_page_two: bool = False,
    page_two_shift: float = 0.0,
    page_two_landscape: bool = False,
) -> bytes:
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    pdf = canvas.Canvas(buf)
    shift = 0.0

    def header() -> None:
        pdf.drawString(50 + shift, 520, "Date")
        pdf.drawString(120 + shift, 520, "Description")
        pdf.drawString(280 + shift, 520, debit_header)
        pdf.drawString(380 + shift, 520, credit_header)
        pdf.drawString(480 + shift, 520, "Balance")

    def rows(first: str, second: str) -> None:
        pdf.drawString(50 + shift, 500, "01/07")
        pdf.drawString(120 + shift, 500, first)
        pdf.drawString(280 + shift, 500, "10.00")
        pdf.drawString(480 + shift, 500, "990.00")
        pdf.drawString(50 + shift, 480, "02/07")
        pdf.drawString(120 + shift, 480, second)
        pdf.drawString(380 + shift, 480, "100.00")
        pdf.drawString(480 + shift, 480, "1090.00")

    header()
    rows("COFFEE SHOP", "PAYROLL")
    pdf.showPage()
    shift = page_two_shift
    if page_two_landscape:
        pdf.setPageSize((842, 595))
    if header_on_page_two:
        header()
    rows("BOOK STORE", "REFUND")
    pdf.save()
    return buf.getvalue()


def _flat_pages(content: bytes) -> list[str]:
    document = fitz.open(stream=content, filetype="pdf")
    try:
        return [page.get_text(sort=True) for page in document]
    finally:
        document.close()


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
    assert offsets == (0, 0), offsets


@pytest.mark.no_db
def test_AC_extraction_3112_later_pages_keep_the_column_layout_of_the_header_page():
    """AC-extraction.3112.2: a page without headers keeps the column positions of the earlier header page."""
    pages = read_pdf_text_pages(_table_pdf("Debit", "Credit"))
    assert pages is not None and len(pages) == 2
    offsets = _amount_offsets(pages[0], "Debit", "Credit", pages[1], ("BOOK STORE", "REFUND"))
    assert offsets == (0, 0), offsets
    # Control: without the document layout, the flat text of the same page is off by more than 2 characters.
    assert max(_amount_offsets(pages[0], "Debit", "Credit", _flat_pages(_table_pdf("Debit", "Credit"))[1], ("BOOK STORE", "REFUND"))) > 2


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
def test_page_two_table_at_another_place_keeps_its_columns():
    """A continuation page whose table sits 40 points to the right keeps its columns: the margin is the page's own."""
    content = _table_pdf("Debit", "Credit", page_two_shift=40.0)
    pages = read_pdf_text_pages(content)
    assert pages is not None
    assert _amount_offsets(pages[0], "Debit", "Credit", pages[1], ("BOOK STORE", "REFUND")) == (0, 0)


@pytest.mark.no_db
def test_page_of_another_width_keeps_the_flat_text():
    """A landscape continuation page has no known column geometry: it keeps the sorted flat text."""
    content = _table_pdf("Debit", "Credit", page_two_shift=120.0, page_two_landscape=True)
    pages = read_pdf_text_pages(content)
    assert pages is not None and len(pages) == 2
    assert pages[1] == _flat_pages(content)[1]
    assert pages[0] != _flat_pages(content)[0]


def _row_suffix_pdf() -> bytes:
    """A table whose rows end the amounts with Dr and Cr, at spread columns that a column render would pad."""
    document = fitz.open()
    page = document.new_page()
    rows = (("01/07", "COFFEE SHOP", "10.00 Dr", "990.00 Cr"), ("02/07", "PAYROLL", "100.00 Cr", "1090.00 Cr"))
    for index, cells in enumerate(rows):
        for x, text in zip((50, 120, 280, 480), cells, strict=True):
            page.insert_text((x, 72 + 16 * index), text)
    data = document.tobytes()
    document.close()
    return data


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("debit_header", "credit_header"),
    [
        ("Debit", "Notes"),
        ("Dr", "Notes"),
        ("Credit money outstanding", "Notes"),
        ("Debit money invested", "Notes"),
        ("Total debits 10.00 unpaid interest", "Notes"),
    ],
)
def test_a_header_that_is_not_a_dual_pair_keeps_the_flat_text(debit_header, credit_header):
    """One-sided headers, and header words inside longer words, do not switch the column rendering on."""
    content = _table_pdf(debit_header, credit_header)
    assert read_pdf_text_pages(content) == _flat_pages(content)


@pytest.mark.no_db
def test_dr_and_cr_after_an_amount_are_not_headers():
    """A single-amount statement that prints ``990.00 Cr`` on its rows keeps the flat text."""
    content = _row_suffix_pdf()
    assert read_pdf_text_pages(content) == _flat_pages(content)
