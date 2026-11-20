"""Read the text layer of a PDF (#2394).

The text layer is an independent source of the numbers that a document prints. The
closing-balance source check compares the stored closing balance with it.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.extraction.extension._base import logger

Word = tuple[float, float, float, float, str]

# A header is one token or one phrase of a line. Tokens are lower-case, without a trailing ":" or ".".
_DEBIT_HEADERS = frozenset(
    {"debit", "debits", "débit", "débits", "withdrawal", "withdrawals", "outflow", "outflows", "dr"}
)
_CREDIT_HEADERS = frozenset(
    {"credit", "credits", "crédit", "crédits", "deposit", "deposits", "inflow", "inflows", "cr"}
)
_DEBIT_PHRASES = ("paid out", "money out")
_CREDIT_PHRASES = ("paid in", "money in")
_HEADER_SCAN_LINES = 25


@dataclass(frozen=True, slots=True)
class _ColumnLayout:
    """The geometry that maps an x position to a text column. One layout serves a whole document."""

    left_margin: float
    char_width: float


def _has_dual_amount_headers(lines: list[list[Word]]) -> bool:
    for row in lines[:_HEADER_SCAN_LINES]:
        tokens = [w[4].strip().lower().rstrip(":.") for w in row]
        line = " ".join(tokens)
        has_debit = bool(_DEBIT_HEADERS.intersection(tokens)) or any(phrase in line for phrase in _DEBIT_PHRASES)
        has_credit = bool(_CREDIT_HEADERS.intersection(tokens)) or any(phrase in line for phrase in _CREDIT_PHRASES)
        if has_debit and has_credit:
            return True
    return False


def _visual_lines(page) -> list[list[Word]]:
    raw_words = page.get_text("words") or []
    words = sorted(
        [(float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])) for w in raw_words],
        key=lambda item: (round(item[1], 1), item[0]),
    )
    visual_lines: list[list[Word]] = []
    for word in words:
        if visual_lines and abs(word[1] - visual_lines[-1][0][1]) <= 3.0:
            visual_lines[-1].append(word)
        else:
            visual_lines.append([word])
    for row in visual_lines:
        row.sort(key=lambda item: item[0])
    return visual_lines


def _column_layout(lines: list[list[Word]]) -> _ColumnLayout:
    words = [word for row in lines for word in row]
    total_width = sum(max(0.0, w[2] - w[0]) for w in words)
    total_chars = sum(len(w[4]) for w in words)
    return _ColumnLayout(
        left_margin=min(w[0] for w in words),
        char_width=max(3.5, total_width / total_chars) if total_chars else 5.5,
    )


def _render_columns(lines: list[list[Word]], layout: _ColumnLayout) -> str:
    rendered_lines: list[str] = []
    for row in lines:
        buf: list[str] = []
        cursor = 0
        prev_x1: float | None = None
        for x0, _y0, x1, _y1, token in row:
            if prev_x1 is None:
                target_col = max(0, round((x0 - layout.left_margin) / layout.char_width))
            elif x0 - prev_x1 <= layout.char_width * 1.4:
                target_col = cursor + 1
            else:
                target_col = max(cursor + 1, round((x0 - layout.left_margin) / layout.char_width))
            if target_col > cursor:
                buf.append(" " * (target_col - cursor))
                cursor = target_col
            buf.append(token)
            cursor += len(token)
            prev_x1 = x1
        rendered_lines.append("".join(buf))
    return "\n".join(rendered_lines)


def _extract_document_text(document) -> list[str]:
    """Return the text of each page. From the first page with dual debit and credit headers, keep the columns.

    The layout is a fact of the document, not of a page: a continuation page does not repeat the
    headers, and its amounts must stay in the columns of the header page (#2987, #3112). Pages before
    the first header page, and a document without such headers, keep the sorted flat text.
    """
    layout: _ColumnLayout | None = None
    pages: list[str] = []
    for page in document:
        lines = _visual_lines(page)
        if layout is None and lines and _has_dual_amount_headers(lines):
            layout = _column_layout(lines)
        if layout is None or not lines:
            pages.append(page.get_text(sort=True) or "")
        else:
            pages.append(_render_columns(lines, layout))
    return pages


def read_pdf_text_pages(file_content: bytes | None, *, max_pages: int | None = None) -> list[str] | None:
    """Return the text of each PDF page, or None when the PDF has no readable text.

    ``sort=True`` puts the cells of one table row on one line. Without it a table drawn column by column
    lists all dates, then all descriptions, then all amounts, and a reader must pair them by position.

    With ``max_pages`` set, a PDF above that page count returns None. The vision
    extraction fails above the same count anyway.
    """
    if not file_content:
        return None
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF is unavailable; skipping the PDF text layer")
        return None
    try:
        document = fitz.open(stream=file_content, filetype="pdf")
    except Exception as exc:
        logger.info("PDF text layer could not be opened", error_type=type(exc).__name__)
        return None
    try:
        if max_pages is not None and len(document) > max_pages:
            return None
        return _extract_document_text(document)
    except Exception as exc:
        logger.info("PDF text layer could not be read", error_type=type(exc).__name__)
        return None
    finally:
        document.close()


def read_pdf_text_layer(file_content: bytes | None, *, max_pages: int | None = None) -> str | None:
    """Return the text layer of a PDF as one string, or None when the PDF has no readable text."""
    pages = read_pdf_text_pages(file_content, max_pages=max_pages)
    return "\n".join(pages) if pages is not None else None
