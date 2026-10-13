"""AC-extraction.closing-balance-source.2: parse_document checks the closing balance against the PDF text (#2394).

The model returned the closing balance that it computed from the rows (4837.50). The PDF printed
4837.55. The balance chain tied out, so the statement scored high enough to be approved. The check
must send such a statement to review and must leave a statement whose closing balance the PDF prints
unchanged.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import fitz
import pytest

from src.extraction import DocumentSource
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
FLAGGED_REASON = "Closing balance 4837.50 is not in the document text"


@pytest.fixture
def service() -> ExtractionService:
    return ExtractionService()


def _payload(closing: str) -> dict:
    return {
        "institution": "Stage One Routing Bank",
        "account_last4": "7702",
        "currency": "SGD",
        "period_start": "2026-05-01",
        "period_end": "2026-05-31",
        "opening_balance": "2000.00",
        "closing_balance": closing,
        "transactions": [
            {"date": date, "description": description, "amount": amount, "direction": direction}
            for date, description, amount, direction in ROWS
        ],
    }


def _statement_pdf(printed_closing: str) -> bytes:
    lines = [
        "Stage One Routing Bank",
        "Account 5551-234-7702",
        "Statement period 2026-05-01 to 2026-05-31",
        "Opening Balance 2000.00",
        *(f"{date} {description} {amount}" for date, description, amount, _direction in ROWS),
        f"Closing Balance {printed_closing}",
        f"Closing Balance {printed_closing}",
    ]
    document = fitz.open()
    page = document.new_page()
    for index, line in enumerate(lines):
        page.insert_text((72, 72 + 16 * index), line)
    content = document.tobytes()
    document.close()
    return content


async def _parse(service: ExtractionService, tmp_path, *, content: bytes, payload: dict, file_type: str = "pdf"):
    path = tmp_path / f"statement.{file_type}"
    path.write_bytes(content)
    with patch.object(service, "extract_financial_data", new=AsyncMock(return_value=payload)):
        return await service.parse_document(
            DocumentSource.resolve(path=path, content=content),
            institution="Stage One Routing Bank",
            user_id=uuid4(),
            file_type=file_type,
        )


async def test_AC_extraction_closing_balance_source_2_computed_closing_goes_to_review(service, tmp_path):
    """The #2394 shape: the PDF prints 4837.55 and the model stored 4837.50."""
    result = await _parse(service, tmp_path, content=_statement_pdf("4837.55"), payload=_payload(COMPUTED_CLOSING))

    assert result.confidence <= Decimal("0.59")
    assert FLAGGED_REASON in result.review_reasons


async def test_AC_extraction_closing_balance_source_2_printed_closing_keeps_high_confidence(service, tmp_path):
    result = await _parse(
        service, tmp_path, content=_statement_pdf(COMPUTED_CLOSING), payload=_payload(COMPUTED_CLOSING)
    )

    assert result.confidence >= Decimal("0.85")
    assert result.review_reasons == ()


async def test_AC_extraction_closing_balance_source_2_unreadable_text_layer_changes_nothing(service, tmp_path):
    """Bytes that are not a PDF give no text layer. The check must not flag the statement."""
    result = await _parse(service, tmp_path, content=b"dummy", payload=_payload(COMPUTED_CLOSING))

    assert result.confidence >= Decimal("0.85")
    assert result.review_reasons == ()


async def test_AC_extraction_closing_balance_source_2_image_upload_is_not_checked(service, tmp_path):
    """Only a PDF carries a text layer. A PNG upload keeps its old routing."""
    result = await _parse(
        service,
        tmp_path,
        content=_statement_pdf("4837.55"),
        payload=_payload(COMPUTED_CLOSING),
        file_type="png",
    )

    assert result.confidence >= Decimal("0.85")
    assert result.review_reasons == ()


async def test_AC_extraction_closing_balance_source_2_flag_is_counted(service, tmp_path):
    """The metric gives the real-world rate of the flag, which issue #2394 lists as unknown."""
    with patch("src.extraction.extension.service.record_financial_invariant_violation") as record:
        await _parse(service, tmp_path, content=_statement_pdf("4837.55"), payload=_payload(COMPUTED_CLOSING))

    assert [call.kwargs["kind"] for call in record.call_args_list] == ["closing_balance_not_in_source"]
    assert "closing_balance_not_in_source" in telemetry_metrics.INVARIANT_VIOLATION_KINDS
