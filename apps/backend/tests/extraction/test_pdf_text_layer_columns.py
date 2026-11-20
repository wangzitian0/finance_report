"""The text layer of a PDF keeps the amount columns of one document (#3112, #2987)."""

from __future__ import annotations

from decimal import Decimal
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
    assert (
        max(
            _amount_offsets(
                pages[0], "Debit", "Credit", _flat_pages(_table_pdf("Debit", "Credit"))[1], ("BOOK STORE", "REFUND")
            )
        )
        > 2
    )


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


def _row(page: str, description: str) -> str:
    return next(line for line in page.splitlines() if description in line)


def _pdf(*pages: list[tuple[float, float, str, str]]) -> bytes:
    """Build a PDF. Each page is a list of (x, y, text, "l" or "r"): text that starts or ends at x."""
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    pdf = canvas.Canvas(buf)
    for page in pages:
        for x, y, text, align in page:
            (pdf.drawRightString if align == "r" else pdf.drawString)(x, y, text)
        pdf.showPage()
    pdf.save()
    return buf.getvalue()


def _left_table(debit_x: float = 280, credit_x: float = 380, balance_x: float = 480, **extra) -> list:
    """A table with left-aligned headers and amounts: one debit row and one credit row, each with a balance."""
    return [
        (50, 520, "Date", "l"),
        (120, 520, "Description", "l"),
        (debit_x, 520, extra.get("debit_header", "Debit"), "l"),
        (credit_x, 520, extra.get("credit_header", "Credit"), "l"),
        (balance_x, 520, "Balance", "l"),
        (50, 500, "01/07", "l"),
        (120, 500, "COFFEE SHOP", "l"),
        (debit_x, 500, "10.00", "l"),
        (balance_x, 500, "990.00", "l"),
        (50, 480, "02/07", "l"),
        (120, 480, "PAYROLL", "l"),
        (credit_x, 480, "100.00", "l"),
        (balance_x, 480, "1090.00", "l"),
    ]


def _marks(line: str) -> list[str]:
    """Return each marked amount of a line with its mark, and nothing else."""
    words = line.split()
    return [f"{words[i - 1]} {word}" for i, word in enumerate(words) if word in ("[Debit]", "[Credit]")]


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("debit_header", "credit_header", "page_two_shift"),
    [("Debit", "Credit", 0.0), ("Paid out", "Paid in", 0.0), ("Debit Amt", "Credit Amt", 40.0)],
)
def test_AC_extraction_3112_an_amount_carries_the_mark_of_its_column(debit_header, credit_header, page_two_shift):
    """AC-extraction.3112.3: debit and credit amounts carry a column mark on every page; a balance carries none.

    A page whose table sits at another place carries the marks when it repeats the header.
    """
    content = _table_pdf(
        debit_header, credit_header, page_two_shift=page_two_shift, header_on_page_two=bool(page_two_shift)
    )
    pages = read_pdf_text_pages(content)
    assert pages is not None and len(pages) == 2
    for page, (debit_row, credit_row) in zip(
        pages, (("COFFEE SHOP", "PAYROLL"), ("BOOK STORE", "REFUND")), strict=True
    ):
        assert _marks(_row(page, debit_row)) == ["10.00 [Debit]"]
        assert _marks(_row(page, credit_row)) == ["100.00 [Credit]"]
        assert _row(page, debit_row).rstrip().endswith("990.00")
        assert _row(page, credit_row).rstrip().endswith("1090.00")


@pytest.mark.no_db
def test_a_shifted_page_without_a_header_carries_no_mark():
    """A table at another x on a page with no header has no known columns: no mark, not a wrong mark."""
    pages = read_pdf_text_pages(_table_pdf("Debit", "Credit", page_two_shift=70.0))
    assert pages is not None
    assert _marks(_row(pages[0], "COFFEE SHOP")) == ["10.00 [Debit]"]
    assert _marks(_row(pages[1], "BOOK STORE")) == [] and _marks(_row(pages[1], "REFUND")) == []


@pytest.mark.no_db
@pytest.mark.parametrize(
    "above",
    [
        [(50, 560, "Total Debits 10.00", "l"), (280, 560, "Total Credits 100.00", "l")],
        [(50, 560, "Each debit or credit shown is final.", "l")],
        [(50, 560, "Total", "l"), (280, 560, "77.00", "l")],
    ],
    ids=["summary_with_totals", "sentence", "number_under_the_debit_column"],
)
def test_a_line_above_the_table_is_no_header_and_carries_no_mark(above):
    """A summary or a sentence that names debit and credit is not the table header; the rows keep their marks."""
    pages = read_pdf_text_pages(_pdf([*above, *_left_table()]))
    assert pages is not None
    lines = pages[0].splitlines()
    header_at = next(i for i, line in enumerate(lines) if "Description" in line)
    assert [_marks(line) for line in lines[:header_at]] == [[] for _ in lines[:header_at]]
    assert _marks(_row(pages[0], "COFFEE SHOP")) == ["10.00 [Debit]"]
    assert _marks(_row(pages[0], "PAYROLL")) == ["100.00 [Credit]"]


@pytest.mark.no_db
def test_right_aligned_amounts_under_headers_of_several_words_carry_the_right_mark():
    """The whole header cell is the column: `Withdrawals (SGD)` ends where its amounts end."""
    page = [
        (50, 520, "Date", "l"),
        (120, 520, "Description", "l"),
        (360, 520, "Withdrawals (SGD)", "r"),
        (450, 520, "Deposits (SGD)", "r"),
        (540, 520, "Balance (SGD)", "r"),
        (50, 500, "01/07", "l"),
        (120, 500, "COFFEE", "l"),
        (360, 500, "10.00", "r"),
        (540, 500, "990.00", "r"),
        (50, 480, "02/07", "l"),
        (120, 480, "PAYROLL", "l"),
        (450, 480, "1,234,567.00", "r"),
        (540, 480, "1,235,557.00", "r"),
    ]
    pages = read_pdf_text_pages(_pdf(page))
    assert pages is not None
    assert _marks(_row(pages[0], "COFFEE")) == ["10.00 [Debit]"]
    assert _marks(_row(pages[0], "PAYROLL")) == ["1,234,567.00 [Credit]"]


@pytest.mark.no_db
def test_a_balance_column_next_to_the_credit_header_carries_no_mark():
    pages = read_pdf_text_pages(_pdf(_left_table(debit_x=300, credit_x=400, balance_x=445)))
    assert pages is not None
    assert _marks(_row(pages[0], "COFFEE SHOP")) == ["10.00 [Debit]"]
    assert _marks(_row(pages[0], "PAYROLL")) == ["100.00 [Credit]"]


@pytest.mark.no_db
def test_a_number_that_is_no_amount_of_the_two_columns_carries_no_mark():
    """A year, a unit price beside the column, a reference and a page number are not debit or credit amounts."""
    page = [
        *_left_table(),
        (50, 460, "03/07", "l"),
        (120, 460, "TAX REFUND FOR", "l"),
        (250, 460, "2025", "l"),
        (50, 440, "04/07", "l"),
        (120, 440, "UNITS", "l"),
        (240, 440, "12.50", "l"),
        (50, 420, "05/07", "l"),
        (120, 420, "REF", "l"),
        (280, 420, "91234567", "l"),
        (280, 40, "1", "l"),
    ]
    pages = read_pdf_text_pages(_pdf(page))
    assert pages is not None
    marked = [mark for line in pages[0].splitlines() for mark in _marks(line)]
    assert marked == ["10.00 [Debit]", "100.00 [Credit]"]


@pytest.mark.no_db
def test_an_amount_with_spaced_thousands_keeps_one_mark_after_the_whole_amount():
    """`1 935,30` is two PDF words and one amount: the mark follows the amount, and the number stays whole."""
    from src.extraction.base.source_balance_check import text_money_values

    page = [
        (50, 520, "Date", "l"),
        (120, 520, "Libellé", "l"),
        (280, 520, "Débit", "l"),
        (380, 520, "Crédit", "l"),
        (480, 520, "Solde", "l"),
        (50, 500, "02/05", "l"),
        (120, 500, "LOYER", "l"),
        (280, 500, "1 935,30", "l"),
        (480, 500, "8 064,70", "l"),
        (50, 480, "03/05", "l"),
        (120, 480, "SALAIRE", "l"),
        (380, 480, "2 000,00", "l"),
        (480, 480, "10 064,70", "l"),
    ]
    content = _pdf(page)
    marked = "\n".join(read_pdf_text_pages(content) or [])
    assert _marks(_row(marked, "LOYER")) == ["935,30 [Debit]"] and "1 935,30 [Debit]" in _row(marked, "LOYER")
    assert "2 000,00 [Credit]" in _row(marked, "SALAIRE")
    assert text_money_values(marked) == text_money_values("\n".join(_flat_pages(content)))
    assert Decimal("1935.30") in text_money_values(marked)


@pytest.mark.no_db
def test_a_marked_text_keeps_every_printed_number_for_the_source_checks():
    """The marks add no number and hide none: the money values of the text are those of the flat text."""
    from src.extraction.base.source_balance_check import text_money_values

    content = _table_pdf("Debit", "Credit")
    marked = "\n".join(read_pdf_text_pages(content) or [])
    assert "[Debit]" in marked
    assert text_money_values(marked) == text_money_values("\n".join(_flat_pages(content)))


@pytest.mark.no_db
def test_an_amount_that_fits_both_headers_carries_no_mark():
    """The amount starts where the debit header starts and ends where the credit header ends: no mark."""
    import fitz as _fitz

    probe = _fitz.open(stream=_pdf([(280, 520, "Debit", "l"), (320, 520, "Credit", "l")]), filetype="pdf")
    credit_right = max(word[2] for word in probe[0].get_text("words"))
    probe.close()
    page = [
        (50, 520, "Date", "l"),
        (280, 520, "Debit", "l"),
        (320, 520, "Credit", "l"),
        (50, 500, "01/07", "l"),
        (credit_right, 500, "1,234,567.00", "r"),
        (50, 480, "02/07", "l"),
        (280, 480, "10.00", "l"),
    ]
    pages = read_pdf_text_pages(_pdf(page))
    assert pages is not None
    wide = _row(pages[0], "01/07")
    assert "1,234,567.00" in wide and _marks(wide) == []
    assert _marks(_row(pages[0], "02/07")) == ["10.00 [Debit]"]
