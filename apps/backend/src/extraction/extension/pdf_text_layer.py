"""Read the text layer of a PDF (#2394).

The text layer is an independent source of the numbers that a document prints. The
closing-balance source check compares the stored closing balance with it.
"""

from __future__ import annotations

from src.extraction.extension._base import logger

_DEBIT_HEADERS = frozenset({"debit", "debits", "withdrawal", "withdrawals", "outflow", "outflows"})
_CREDIT_HEADERS = frozenset({"credit", "credits", "deposit", "deposits", "inflow", "inflows"})


def _has_dual_amount_headers(lines: list[list[tuple[float, float, float, float, str]]]) -> bool:
    for row in lines[:25]:
        tokens = {w[4].strip().lower().rstrip(":") for w in row}
        if (tokens & _DEBIT_HEADERS) and (tokens & _CREDIT_HEADERS):
            return True
    return False


def _extract_page_text(page) -> str:
    """Extract page text preserving exact horizontal columns when dual Debit/Credit headers exist (#2987)."""
    raw_words = page.get_text("words") or []
    if not raw_words:
        return page.get_text(sort=True) or ""

    words = sorted(
        [(float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])) for w in raw_words],
        key=lambda item: (round(item[1], 1), item[0]),
    )
    visual_lines: list[list[tuple[float, float, float, float, str]]] = []
    for word in words:
        if visual_lines and abs(word[1] - visual_lines[-1][0][1]) <= 3.0:
            visual_lines[-1].append(word)
        else:
            visual_lines.append([word])
    for row in visual_lines:
        row.sort(key=lambda item: item[0])

    if not _has_dual_amount_headers(visual_lines):
        return page.get_text(sort=True) or ""

    total_width = sum(max(0.0, w[2] - w[0]) for w in words)
    total_chars = sum(len(w[4]) for w in words)
    char_width = max(3.5, total_width / total_chars) if total_chars else 5.5
    left_margin = min(w[0] for w in words)

    rendered_lines: list[str] = []
    for row in visual_lines:
        buf: list[str] = []
        cursor = 0
        prev_x1: float | None = None
        for x0, _y0, x1, _y1, token in row:
            if prev_x1 is None:
                target_col = max(0, round((x0 - left_margin) / char_width))
            elif x0 - prev_x1 <= char_width * 1.4:
                target_col = cursor + 1
            else:
                target_col = max(cursor + 1, round((x0 - left_margin) / char_width))
            if target_col > cursor:
                buf.append(" " * (target_col - cursor))
                cursor = target_col
            buf.append(token)
            cursor += len(token)
            prev_x1 = x1
        rendered_lines.append("".join(buf))
    return "\n".join(rendered_lines)


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
        return [_extract_page_text(page) for page in document]
    except Exception as exc:
        logger.info("PDF text layer could not be read", error_type=type(exc).__name__)
        return None
    finally:
        document.close()


def read_pdf_text_layer(file_content: bytes | None, *, max_pages: int | None = None) -> str | None:
    """Return the text layer of a PDF as one string, or None when the PDF has no readable text."""
    pages = read_pdf_text_pages(file_content, max_pages=max_pages)
    return "\n".join(pages) if pages is not None else None
