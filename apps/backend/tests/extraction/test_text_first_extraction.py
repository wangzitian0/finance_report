"""Text-first extraction of a PDF with a text layer (#2987, #2983)."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, patch

import fitz
import pytest

from src.config import settings
from src.extraction.base.paged_extraction import build_paged_meta_prompt, build_paged_prompt
from src.extraction.base.validation import DuplicateCurrencyError, bank_currency_balances
from src.extraction.extension._base import ExtractionError
from src.extraction.extension.prompts.statement import SYSTEM_PROMPT, get_parsing_prompt
from src.extraction.extension.service import ExtractionService

ROW = "15 Jan SALARY ACME CORP 5,000.00 CR"


def _pdf(pages: list[str]) -> bytes:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _column_major_table_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    rows = [("24/07", "SAVORY MORNING", "2.90"), ("25/07", "METRO TRANSIT", "17.16"), ("25/07", "SUNNY CAFE", "17.40")]
    for col, x in enumerate((72, 160, 420)):
        for idx, row in enumerate(rows):
            page.insert_text((x, 120 + idx * 18), row[col])
    data = doc.tobytes()
    doc.close()
    return data


def _service() -> ExtractionService:
    svc = ExtractionService()
    svc.api_key, svc.multimodal_model = "test-key", "test-model"
    return svc


def _image_batches(*_args, **_kwargs):
    return [[{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]]


def _parts(messages) -> list[dict]:
    return [part for msg in messages for part in msg["content"]]


def _has_image(messages) -> bool:
    return any("image" in str(part.get("type", "")) for part in _parts(messages))


def _text_of(messages) -> str:
    return "\n".join(str(part.get("text", "")) for part in _parts(messages))


async def _extract(service, content: bytes, *, file_type: str = "pdf", **kwargs):
    model_call = AsyncMock(return_value={"institution": "DBS", "transactions": [{"amount": "5000.00"}]})
    with (
        patch.object(service, "_extract_json_with_model", model_call),
        patch.object(service, "_build_vision_media_payload_batches", _image_batches),
    ):
        return await service.extract_financial_data(
            file_content=content, institution="DBS", file_type=file_type, **kwargs
        ), model_call


async def test_AC_extraction_2987_1_text_layer_and_table_row_reaches_model_as_text():
    _, model_call = await _extract(_service(), _pdf([ROW]))
    messages = model_call.await_args_list[0].kwargs["messages"]
    text = _text_of(messages)
    assert not _has_image(messages) and "SALARY ACME CORP" in text and "5,000.00" in text

    _, table_call = await _extract(_service(), _column_major_table_pdf())
    table_text = _text_of(table_call.await_args_list[0].kwargs["messages"])
    lines = [line for line in table_text.split("\n") if any(k in line for k in ("SAVORY", "METRO", "SUNNY"))]
    assert (
        len(lines) == 3
        and all(re.search(r"\d\d/07\s+[A-Z ]+\s+\d+\.\d\d", ln) for ln in lines)
        and "17.16" in lines[1]
        and "METRO TRANSIT" in lines[1]
    )


@pytest.mark.parametrize(
    ("content_fn", "file_type", "kwargs"),
    [
        (lambda: _pdf([""]), "pdf", {}),
        (lambda: _pdf(["Page 1 of 3"]), "pdf", {}),
        (lambda: b"png-bytes", "png", {}),
        (lambda: _pdf([ROW]), "pdf", {"read_text_layer": False}),
    ],
    ids=["blank-pdf", "page-number-only", "png", "skip-text-layer"],
)
async def test_AC_extraction_2987_image_fallback_conditions(content_fn, file_type, kwargs):
    _, model_call = await _extract(_service(), content_fn(), file_type=file_type, **kwargs)
    assert _has_image(model_call.await_args_list[0].kwargs["messages"])


async def test_AC_extraction_2987_5_6_7_retry_fallback_and_paged_batches():
    first = {
        "institution": "DBS",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "0.00",
        "closing_balance": "100.00",
        "currency": "SGD",
        "transactions": [{"date": "2025-01-10", "amount": "87.50", "direction": "IN", "currency": "SGD"}],
    }
    second = {**first, "transactions": [{**first["transactions"][0], "amount": "100.00"}]}
    svc1 = _service()
    mock1 = AsyncMock(side_effect=[first, second])
    with patch.object(settings, "ai_extract_max_attempts", 2), patch.object(svc1, "extract_financial_data", mock1):
        slices1, _ = await svc1._extract_with_balance_retry(
            file_content=b"x", institution=None, file_type="pdf", file_url=None, force_model=None, filename="s.pdf"
        )
    # A balance gap sends the check result to the model, which reads the text again (#2964).
    assert slices1[0].payload is second and [c.kwargs["read_text_layer"] for c in mock1.await_args_list] == [
        True,
        True,
    ]
    assert "The difference is 12.50" in mock1.await_args_list[1].kwargs["feedback"]

    svc2 = _service()
    mock2 = AsyncMock(
        side_effect=[
            {"transactions": []},
            {"institution": "DBS", "transactions": []},
            {"transactions": [{"amount": "5.00"}]},
        ]
    )
    with (
        patch.object(svc2, "_extract_json_with_model", mock2),
        patch.object(svc2, "_build_vision_media_payload_batches", _image_batches),
    ):
        res2 = await svc2.extract_financial_data(file_content=_pdf([ROW]), institution="DBS", file_type="pdf")
    m_first, m_second, m_third = (c.kwargs["messages"] for c in mock2.await_args_list)
    assert (
        not _has_image(m_first)
        and _has_image(m_second)
        and _has_image(m_third)
        and res2["transactions"] == [{"amount": "5.00"}]
    )

    svc3 = _service()
    mock3 = AsyncMock(
        side_effect=[
            {"institution": "DBS"},
            {"transactions": [{"amount": "1.00"}]},
            {"transactions": [{"amount": "2.00"}]},
        ]
    )
    with patch.object(svc3, "_extract_json_with_model", mock3):
        merged = await svc3.extract_financial_data(
            file_content=_pdf([f"{ROW} page {n}" for n in range(1, 8)]), institution="DBS", file_type="pdf"
        )
    msgs = [c.kwargs["messages"] for c in mock3.await_args_list]
    assert len(msgs) == 3 and not any(_has_image(m) for m in msgs) and len(merged["transactions"]) == 2
    assert (
        "[Page 1]" in _text_of(msgs[1])
        and "[Page 5]" in _text_of(msgs[1])
        and "[Page 6]" in _text_of(msgs[2])
        and "[Page 7]" in _text_of(msgs[2])
    )


def test_AC_extraction_2987_8_9_10_prompts():
    bank_prompt = get_parsing_prompt("DBS", document_kind="bank")
    assert all(f not in bank_prompt for f in ("suggested_category", "category_confidence", "raw_text"))
    assert (
        "balance_after" in bank_prompt
        and "reference" in bank_prompt
        and "combine them into one response" not in SYSTEM_PROMPT
    )
    meta = build_paged_meta_prompt("BASE", page_numbers=[1, 2, 7], total_pages=7)
    batch = build_paged_prompt(
        "BASE", part_index=2, part_count=2, page_start=6, page_end=7, total_pages=7, has_context_page=True
    )
    assert "image" not in meta.lower() and "image" not in batch.lower()


async def test_AC_extraction_2983_5_duplicate_currency_balances_stop_the_retry():
    duplicate = {
        "institution": "BNP",
        "balances": [
            {"currency": "EUR", "opening": "100.00", "closing": "238.52"},
            {"currency": "EUR", "opening": "200.00", "closing": "403.12"},
        ],
        "transactions": [],
    }
    with pytest.raises(DuplicateCurrencyError, match="EUR"):
        bank_currency_balances(duplicate)
    service = _service()
    mock = AsyncMock(side_effect=[duplicate, duplicate])
    with (
        patch.object(settings, "ai_extract_max_attempts", 2),
        patch.object(service, "extract_financial_data", mock),
        pytest.raises(ExtractionError, match="one account per file"),
    ):
        await service._extract_with_balance_retry(
            file_content=b"x", institution=None, file_type="pdf", file_url=None, force_model=None, filename="s.pdf"
        )
    assert mock.await_count == 1


@pytest.mark.no_db
def test_AC_extraction_2987_column_aligned_debit_credit_preserves_horizontal_separation():
    """#2987: Tables with Debit and Credit headers preserve column spacing so values align under their column."""
    from io import BytesIO
    from reportlab.pdfgen import canvas
    from src.extraction.extension.pdf_text_layer import read_pdf_text_pages

    buf = BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.drawString(50, 720, "Date")
    pdf.drawString(120, 720, "Description")
    pdf.drawString(280, 720, "Debit")
    pdf.drawString(360, 720, "Credit")
    pdf.drawString(440, 720, "Balance")
    pdf.drawString(50, 700, "01/07")
    pdf.drawString(120, 700, "COFFEE SHOP")
    pdf.drawString(280, 700, "10.00")
    pdf.drawString(440, 700, "990.00")
    pdf.drawString(50, 680, "02/07")
    pdf.drawString(120, 680, "PAYROLL")
    pdf.drawString(360, 680, "100.00")
    pdf.drawString(440, 680, "1090.00")
    pdf.save()

    pages = read_pdf_text_pages(buf.getvalue())
    assert pages is not None and len(pages) == 1
    lines = [line for line in pages[0].splitlines() if line.strip()]
    header = next(line for line in lines if "Debit" in line and "Credit" in line)
    debit_line = next(line for line in lines if "COFFEE SHOP" in line)
    credit_line = next(line for line in lines if "PAYROLL" in line)
    assert credit_line.index("100.00") - debit_line.index("10.00") >= 5
    assert abs(header.index("Credit") - credit_line.index("100.00")) <= abs(
        header.index("Debit") - credit_line.index("100.00")
    )


async def test_brokerage_pdf_with_positions_only_stays_on_text_layer():
    """Brokerage PDFs whose text layer extracts holdings without transactions must not fall back to vision."""
    service = _service()
    position_payload = {
        "institution": "Moomoo",
        "currency": "USD",
        "period_start": "2025-06-01",
        "period_end": "2025-06-30",
        "transactions": [],
        "positions": [{"symbol": "AAPL", "quantity": "10", "market_value": "1900.00", "currency": "USD"}],
    }
    model_call = AsyncMock(return_value=position_payload)
    vision_builder_called = False

    def fail_if_vision_called(*_args, **_kwargs):
        nonlocal vision_builder_called
        vision_builder_called = True
        return _image_batches()

    with (
        patch.object(service, "_extract_json_with_model", model_call),
        patch.object(service, "_build_vision_media_payload_batches", fail_if_vision_called),
    ):
        result = await service.extract_financial_data(
            file_content=_pdf([ROW]), institution="Moomoo", file_type="pdf", filename="moomoo-positions.pdf"
        )
    assert vision_builder_called is False
    assert model_call.await_count == 1
    assert not _has_image(model_call.await_args_list[0].kwargs["messages"])
    assert result["positions"] == position_payload["positions"]
