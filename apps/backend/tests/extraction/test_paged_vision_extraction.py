"""AC-extraction.1832.1/.2/.3: paginated full-document vision extraction (#1832).

Staging real-statement QA (2026-07-14): the vision path rendered only the first
``PDF_VISION_MAX_PAGES`` pages and silently dropped the rest, which made the
running-balance chain mathematically guaranteed to fail for any statement longer
than the cap — a mainstream 7-page bank statement could never import. These
tests pin the replacement behavior: every page is rendered, documents longer
than one batch are extracted through one model call per batch and merged, and
documents above the total-page ceiling fail with an explicit error instead of
silent truncation.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest

from src.extraction.base.paged_extraction import build_paged_prompt, merge_paged_extractions
from src.extraction.extension._base import ExtractionError
from src.extraction.extension.service import ExtractionService


def _pdf_with_pages(page_count: int) -> bytes:
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    for index in range(page_count):
        pdf.drawString(72, 720, f"statement fixture page {index + 1}")
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


class TestRenderAllPagesInBatches:
    def test_AC_extraction_1832_1_renders_every_page_batched_by_call_cap(self):
        """AC-extraction.1832.1: a PDF longer than one batch renders ALL pages,
        grouped into per-call batches of PDF_VISION_MAX_PAGES."""
        service = ExtractionService()
        page_count = service.PDF_VISION_MAX_PAGES * 2 + 2  # 12 pages for cap 5

        batches = service._render_pdf_pages_as_image_payload_batches(_pdf_with_pages(page_count))

        assert [len(batch) for batch in batches] == [5, 5, 2]
        rendered = [payload for batch in batches for payload in batch]
        assert len(rendered) == page_count
        assert all(p["image_url"]["url"].startswith("data:image/png;base64,") for p in rendered)

    def test_AC_extraction_1832_3_total_page_ceiling_is_an_explicit_error(self):
        """AC-extraction.1832.3: exceeding PDF_VISION_MAX_TOTAL_PAGES raises an
        honest, page-count-naming error — never silent truncation."""
        service = ExtractionService()
        oversize = service.PDF_VISION_MAX_TOTAL_PAGES + 1

        with pytest.raises(ExtractionError, match=rf"{oversize} pages.*{service.PDF_VISION_MAX_TOTAL_PAGES}-page"):
            service._render_pdf_pages_as_image_payload_batches(_pdf_with_pages(oversize))


class TestMergePagedExtractions:
    def test_AC_extraction_1832_2_merge_semantics(self):
        """AC-extraction.1832.2: transactions concatenate in page order; scalar
        metadata takes the first non-empty value; opening balance comes from the
        first part that saw it, closing balance from the last."""
        parts = [
            {
                "institution": "DBS",
                "account_last4": "0355",
                "currency": "SGD",
                "period_start": "2025-06-01",
                "period_end": "2025-06-30",
                "opening_balance": "100.00",
                "closing_balance": None,
                "transactions": [{"description": "t1"}, {"description": "t2"}],
            },
            {
                "institution": None,
                "currency": "",
                "opening_balance": None,
                "closing_balance": None,
                "transactions": [{"description": "t3"}],
            },
            {
                "institution": "DBS Bank",
                "opening_balance": "999.99",
                "closing_balance": "175.00",
                "transactions": [{"description": "t4"}],
            },
        ]

        merged = merge_paged_extractions(parts)

        assert merged["institution"] == "DBS"  # first non-empty, not overwritten
        assert merged["account_last4"] == "0355"
        assert merged["currency"] == "SGD"
        assert merged["opening_balance"] == "100.00"  # first part wins
        assert merged["closing_balance"] == "175.00"  # last non-empty wins
        assert [t["description"] for t in merged["transactions"]] == ["t1", "t2", "t3", "t4"]

    def test_merge_concatenates_brokerage_positions(self):
        parts = [
            {"positions": [{"symbol": "A"}], "transactions": []},
            {"positions": [{"symbol": "B"}, {"symbol": "C"}], "transactions": []},
        ]
        merged = merge_paged_extractions(parts)
        assert [p["symbol"] for p in merged["positions"]] == ["A", "B", "C"]

    def test_merge_single_part_is_identity(self):
        part = {"institution": "GXS", "transactions": [{"description": "t1"}]}
        assert merge_paged_extractions([part]) is part

    def test_merge_rejects_empty_input(self):
        with pytest.raises(ValueError):
            merge_paged_extractions([])


class TestPagedPrompt:
    def test_single_part_prompt_is_unchanged(self):
        assert build_paged_prompt("BASE", part_index=1, part_count=1, page_start=1, page_end=5, total_pages=5) == "BASE"

    def test_multi_part_prompt_names_pages_and_forbids_page_subtotals(self):
        prompt = build_paged_prompt("BASE", part_index=2, part_count=3, page_start=6, page_end=10, total_pages=12)
        assert prompt.startswith("BASE")
        assert "pages 6-10" in prompt
        assert "12-page" in prompt
        assert "(2/3)" in prompt
        assert "balance-carried-forward" in prompt

    def test_context_page_rule_appears_only_when_carried(self):
        """Scanned statements may not repeat table headers on continuation pages,
        so non-first parts carry page 1 as context — and the prompt must scope it
        to headers/metadata, never transaction extraction."""
        with_context = build_paged_prompt(
            "BASE", part_index=2, part_count=3, page_start=6, page_end=10, total_pages=12, has_context_page=True
        )
        assert "ONLY as context" in with_context
        assert "Do NOT extract transactions from this context page" in with_context
        # PR #1843 review: the header must not claim "only pages X-Y" when a
        # leading context image is also included — that mismatch could confuse
        # the model about the extra image it's seeing.
        assert "only pages 6-10" not in with_context
        assert "the FIRST image below is" in with_context
        without_context = build_paged_prompt(
            "BASE", part_index=1, part_count=3, page_start=1, page_end=5, total_pages=12
        )
        assert "context page" not in without_context


class TestBatchedExtractFlow:
    async def test_AC_extraction_1832_1_multi_batch_pdf_extracts_once_per_batch_and_merges(self, monkeypatch):
        """AC-extraction.1832.1: a document spanning 3 batches produces 3 model
        calls (each with its own part prompt + only its batch's images) whose
        payloads merge into one full-document extraction."""
        from src.config import settings

        monkeypatch.setattr(settings, "ai_provider", "zai")
        service = ExtractionService()
        service.api_key = "test-key"

        page_count = service.PDF_VISION_MAX_PAGES * 2 + 2
        pdf_bytes = _pdf_with_pages(page_count)

        part_payloads = [
            {
                "institution": "DBS",
                "currency": "SGD",
                "opening_balance": "100.00",
                "closing_balance": None,
                "transactions": [{"description": "t1"}],
            },
            {"transactions": [{"description": "t2"}]},
            {"closing_balance": "175.00", "transactions": [{"description": "t3"}]},
        ]
        mock_extract = AsyncMock(side_effect=part_payloads)

        with patch.object(service, "_extract_json_with_models", mock_extract):
            merged = await service.extract_financial_data(pdf_bytes, "DBS", "pdf")

        assert mock_extract.await_count == 3
        first_page_payload = None
        for index, call in enumerate(mock_extract.await_args_list, start=1):
            content = call.kwargs["messages"][0]["content"]
            text = content[0]["text"]
            assert f"({index}/3)" in text
            image_payloads = content[1:]
            if index == 1:
                assert len(image_payloads) == 5
                assert "context page" not in text
                first_page_payload = image_payloads[0]
            else:
                # continuation parts carry page 1 as a leading context image
                # (scanned docs may not repeat table headers per page)
                own_pages = 5 if index < 3 else 2
                assert len(image_payloads) == own_pages + 1
                assert image_payloads[0] == first_page_payload
                assert "Do NOT extract transactions from this context page" in text
        assert merged["institution"] == "DBS"
        assert merged["opening_balance"] == "100.00"
        assert merged["closing_balance"] == "175.00"
        assert [t["description"] for t in merged["transactions"]] == ["t1", "t2", "t3"]

    async def test_single_batch_pdf_keeps_single_call_shape(self, monkeypatch):
        from src.config import settings

        monkeypatch.setattr(settings, "ai_provider", "zai")
        service = ExtractionService()
        service.api_key = "test-key"

        mock_extract = AsyncMock(return_value={"transactions": []})
        with patch.object(service, "_extract_json_with_models", mock_extract):
            await service.extract_financial_data(_pdf_with_pages(2), "DBS", "pdf")

        assert mock_extract.await_count == 1
        text = mock_extract.await_args.kwargs["messages"][0]["content"][0]["text"]
        assert "PARTIAL DOCUMENT" not in text
