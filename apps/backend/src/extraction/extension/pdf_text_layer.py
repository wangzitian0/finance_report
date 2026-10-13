"""Read the text layer of a PDF (#2394).

The text layer is an independent source of the numbers that a document prints. The
closing-balance source check compares the stored closing balance with it.
"""

from __future__ import annotations

from src.extraction.extension._base import logger


def read_pdf_text_layer(file_content: bytes | None, *, max_pages: int) -> str | None:
    """Return the text layer of a PDF, or None when the PDF has no readable text.

    A PDF above ``max_pages`` returns None: its extraction fails anyway.
    """
    if not file_content:
        return None
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF is unavailable; skipping the PDF text layer check")
        return None
    try:
        document = fitz.open(stream=file_content, filetype="pdf")
    except Exception as exc:
        logger.info("PDF text layer could not be opened", error_type=type(exc).__name__)
        return None
    try:
        if len(document) > max_pages:
            return None
        return "\n".join(page.get_text() or "" for page in document)
    except Exception as exc:
        logger.info("PDF text layer could not be read", error_type=type(exc).__name__)
        return None
    finally:
        document.close()
