from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import fitz
import pytest

from src.extraction import DocumentSource
from src.extraction.extension.pdf_text_layer import read_pdf_text_layer
from src.extraction.extension.service import ExtractionService
from src.observability import telemetry_metrics

ROWS = [
    ("2026-05-02", "Salary Acme Pte Ltd", "3000.00", "IN"),
    ("2026-05-03", "Interest", "1.50", "IN"),
    ("2026-05-10", "Grocery Market", "85.40", "OUT"),
    ("2026-05-12", "Phone Plan", "23.60", "OUT"),
    ("2026-05-20", "Coffee House", "55.00", "OUT"),
]
COMPUTED_CLOSING = "4837.50"


def _payload(closing: str) -> dict:
    return {
        "institution": "Stage One Routing Bank", "account_last4": "7702", "currency": "SGD",
        "period_start": "2026-05-01", "period_end": "2026-05-31", "opening_balance": "2000.00", "closing_balance": closing,
        "transactions": [{"date": d, "description": desc, "amount": amt, "direction": dir_} for d, desc, amt, dir_ in ROWS],
    }


def _pdf(lines: list[str]) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 72 + 16 * i), line)
    data = doc.tobytes()
    doc.close()
    return data


def _statement_pdf(printed_closing: str) -> bytes:
    return _pdf(["Stage One Routing Bank", "Account 5551-234-7702", "Statement period 2026-05-01 to 2026-05-31", "Opening Balance 2000.00", *(f"{d} {desc} {amt}" for d, desc, amt, _ in ROWS), f"Closing Balance {printed_closing}", f"Closing Balance {printed_closing}"])


async def _parse(tmp_path, *, content: bytes, payload: dict, file_type: str = "pdf"):
    svc = ExtractionService()
    path = tmp_path / f"statement.{file_type}"
    path.write_bytes(content)
    with patch.object(svc, "extract_financial_data", new=AsyncMock(return_value=payload)):
        return await svc.parse_document(DocumentSource.resolve(path=path, content=content), institution="Stage One Routing Bank", user_id=uuid4(), file_type=file_type)


@pytest.mark.parametrize(
    ("content_fn", "file_type", "review_expected"),
    [
        (lambda: _statement_pdf("4837.55"), "pdf", True),
        (lambda: _statement_pdf(COMPUTED_CLOSING), "pdf", False),
        (lambda: b"dummy", "pdf", False),
        (lambda: _statement_pdf("4837.55"), "png", False),
    ],
    ids=["mismatch-goes-review", "matched-keeps-high", "unreadable-pdf", "png-skipped"],
)
async def test_AC_extraction_closing_balance_source_2_routing(tmp_path, content_fn, file_type, review_expected):
    res = await _parse(tmp_path, content=content_fn(), payload=_payload(COMPUTED_CLOSING), file_type=file_type)
    if review_expected:
        assert res.confidence <= Decimal("0.59") and "Closing balance 4837.50 is not in the document text" in res.review_reasons
    else:
        assert res.confidence >= Decimal("0.85") and res.review_reasons == ()


async def test_AC_extraction_closing_balance_source_2_metric_and_text_layer_reader(tmp_path):
    with patch("src.extraction.extension.service.record_financial_invariant_violation") as record:
        await _parse(tmp_path, content=_statement_pdf("4837.55"), payload=_payload(COMPUTED_CLOSING))
    assert [c.kwargs["kind"] for c in record.call_args_list] == ["closing_balance_not_in_source"] and "closing_balance_not_in_source" in telemetry_metrics.INVARIANT_VIOLATION_KINDS

    doc = fitz.open()
    for text in ("first page 100.00", "second page 200.00"):
        doc.new_page().insert_text((72, 72), text)
    content = doc.tobytes()
    doc.close()
    uncapped = read_pdf_text_layer(content)
    assert uncapped is not None and "100.00" in uncapped and "200.00" in uncapped
    assert (read_pdf_text_layer(content, max_pages=2), read_pdf_text_layer(content, max_pages=1), read_pdf_text_layer(None), read_pdf_text_layer(b"not a pdf")) == (uncapped, None, None, None)
