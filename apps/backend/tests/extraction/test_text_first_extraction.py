"""Text-first extraction of a PDF with a text layer (#2987, #2983).

Evidence of the run of 2026-11-11 on staging: every PDF was rendered to page images and read by
a vision model, although the PDF prints its numbers exactly. The public Monopoly card statement
was rejected in 4 of 4 passes with the same balance gap; the same rows as plain text reconciled
in 4 of 4. The pass costs 74 to 85 completion tokens per row, and a second pass repeated the
same reading.
"""

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
    document = fitz.open()
    for text in pages:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def _column_major_table_pdf() -> bytes:
    """A statement table drawn column by column, as the Monopoly sample draws it: all dates, then all descriptions, then all amounts."""
    document = fitz.open()
    page = document.new_page()
    rows = [("24/07", "SAVORY MORNING", "2.90"), ("25/07", "METRO TRANSIT", "17.16"), ("25/07", "SUNNY CAFE", "17.40")]
    for column, x in enumerate((72, 160, 420)):
        for index, row in enumerate(rows):
            page.insert_text((x, 120 + index * 18), row[column])
    data = document.tobytes()
    document.close()
    return data


def _service() -> ExtractionService:
    service = ExtractionService()
    service.api_key = "test-key"
    service.multimodal_model = "test-model"
    return service


def _image_batches(*_args, **_kwargs):
    return [[{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]]


def _parts(messages) -> list[dict]:
    return [part for message in messages for part in message["content"]]


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
        result = await service.extract_financial_data(
            file_content=content, institution="DBS", file_type=file_type, **kwargs
        )
    return result, model_call


async def test_AC_extraction_2987_1_a_pdf_with_a_text_layer_reaches_the_model_as_text():
    """AC-extraction.2987.1: A PDF with a text layer is sent as page text and carries no image part."""
    _, model_call = await _extract(_service(), _pdf([ROW]))
    (call,) = model_call.await_args_list
    messages = call.kwargs["messages"]
    assert not _has_image(messages)
    assert "SALARY ACME CORP" in _text_of(messages)
    assert "5,000.00" in _text_of(messages)


async def test_AC_extraction_2987_2_a_pdf_without_a_text_layer_takes_the_image_path():
    """AC-extraction.2987.2: A PDF page without text is read as an image."""
    _, model_call = await _extract(_service(), _pdf([""]))
    assert _has_image(model_call.await_args_list[0].kwargs["messages"])


async def test_AC_extraction_2987_11_a_pdf_whose_only_text_is_a_page_number_takes_the_image_path():
    """AC-extraction.2987.11: A scanned page with a page number prints no amount, so the text layer is not used."""
    _, model_call = await _extract(_service(), _pdf(["Page 1 of 3"]))
    assert _has_image(model_call.await_args_list[0].kwargs["messages"])


async def test_AC_extraction_2987_3_a_png_takes_the_image_path():
    """AC-extraction.2987.3: A PNG is read as an image."""
    _, model_call = await _extract(_service(), b"png-bytes", file_type="png")
    assert _has_image(model_call.await_args_list[0].kwargs["messages"])


async def test_AC_extraction_2987_4_a_pass_that_skips_the_text_layer_reads_images():
    """AC-extraction.2987.4: read_text_layer=False reads the images of a PDF that has a text layer."""
    _, model_call = await _extract(_service(), _pdf([ROW]), read_text_layer=False)
    assert _has_image(model_call.await_args_list[0].kwargs["messages"])


async def test_AC_extraction_2987_5_the_first_pass_reads_text_and_the_second_pass_reads_images():
    """AC-extraction.2987.5: The re-extract loop gives the second pass another reader than the first."""
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
    service = _service()
    mock = AsyncMock(side_effect=[first, second])
    with patch.object(settings, "ai_extract_max_attempts", 2), patch.object(service, "extract_financial_data", mock):
        result = await service._extract_with_balance_retry(
            file_content=b"x", institution=None, file_type="pdf", file_url=None, force_model=None, filename="s.pdf"
        )
    assert result is second
    assert [call.kwargs["read_text_layer"] for call in mock.await_args_list] == [True, False]


async def test_AC_extraction_2987_6_a_text_layer_that_yields_no_rows_falls_back_to_the_images():
    """AC-extraction.2987.6: A text layer that yields no rows is not trusted; the same call reads the images."""
    service = _service()
    model_call = AsyncMock(side_effect=[{"transactions": []}, {"transactions": [{"amount": "5.00"}]}])
    with (
        patch.object(service, "_extract_json_with_model", model_call),
        patch.object(service, "_build_vision_media_payload_batches", _image_batches),
    ):
        result = await service.extract_financial_data(file_content=_pdf([ROW]), institution="DBS", file_type="pdf")
    first, second = (call.kwargs["messages"] for call in model_call.await_args_list)
    assert not _has_image(first)
    assert _has_image(second)
    assert result == {"transactions": [{"amount": "5.00"}]}


async def test_AC_extraction_2987_7_a_long_pdf_is_sent_as_text_in_batches_of_five_pages():
    """AC-extraction.2987.7: Seven text pages make one metadata call and two batch calls, all text."""
    service = _service()
    parts = [{"institution": "DBS"}, {"transactions": [{"amount": "1.00"}]}, {"transactions": [{"amount": "2.00"}]}]
    pages = [f"{ROW} page {n}" for n in range(1, 8)]
    model_call = AsyncMock(side_effect=parts)
    with patch.object(service, "_extract_json_with_model", model_call):
        merged = await service.extract_financial_data(file_content=_pdf(pages), institution="DBS", file_type="pdf")
    messages = [call.kwargs["messages"] for call in model_call.await_args_list]
    assert len(messages) == 3
    assert not any(_has_image(m) for m in messages)
    assert "[Page 1]" in _text_of(messages[1]) and "[Page 5]" in _text_of(messages[1])
    assert "[Page 6]" in _text_of(messages[2]) and "[Page 7]" in _text_of(messages[2])
    assert len(merged["transactions"]) == 2


def test_AC_extraction_2987_8_the_bank_prompt_asks_for_no_category_confidence_or_raw_text():
    """AC-extraction.2987.8: No code reads these fields of a bank row, so the prompt does not ask for them."""
    bank_prompt = get_parsing_prompt("DBS", document_kind="bank")
    for field in ("suggested_category", "category_confidence", "raw_text"):
        assert field not in bank_prompt
    assert "balance_after" in bank_prompt and "reference" in bank_prompt


def test_AC_extraction_2987_9_the_prompt_does_not_tell_the_model_to_combine_accounts():
    """AC-extraction.2987.9: The prompt must not contradict the code, which rejects a merged multi-account result."""
    assert "combine them into one response" not in SYSTEM_PROMPT


def test_AC_extraction_2987_10_the_paged_prompts_say_page_and_not_image():
    """AC-extraction.2987.10: One paged prompt serves both the image reader and the text reader."""
    meta = build_paged_meta_prompt("BASE", page_numbers=[1, 2, 7], total_pages=7)
    batch = build_paged_prompt(
        "BASE", part_index=2, part_count=2, page_start=6, page_end=7, total_pages=7, has_context_page=True
    )
    assert "image" not in meta.lower()
    assert "image" not in batch.lower()


async def test_AC_extraction_2983_5_duplicate_currency_balances_stop_the_retry_with_a_message_that_names_the_cause():
    """AC-extraction.2983.5: Two balances in one currency end the extraction after one pass, with a clear message."""
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
    with patch.object(settings, "ai_extract_max_attempts", 2), patch.object(service, "extract_financial_data", mock):
        with pytest.raises(ExtractionError, match="one account per file"):
            await service._extract_with_balance_retry(
                file_content=b"x", institution=None, file_type="pdf", file_url=None, force_model=None, filename="s.pdf"
            )
    assert mock.await_count == 1


async def test_AC_extraction_2987_12_the_cells_of_one_table_row_reach_the_model_on_one_line():
    """AC-extraction.2987.12: Date, description and amount of one row stay on one line of the page text."""
    _, model_call = await _extract(_service(), _column_major_table_pdf())
    text = _text_of(model_call.await_args_list[0].kwargs["messages"])
    lines = [line for line in text.split("\n") if "SAVORY" in line or "METRO" in line or "SUNNY" in line]
    assert len(lines) == 3
    assert all(re.search(r"\d\d/07\s+[A-Z ]+\s+\d+\.\d\d", line) for line in lines)
    assert "17.16" in lines[1] and "METRO TRANSIT" in lines[1]
