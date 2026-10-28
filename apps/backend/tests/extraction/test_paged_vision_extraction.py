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

import gc
import os
import tracemalloc
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


def _scanned_pdf_with_pages(page_count: int, *, width: int = 520, height: int = 700) -> bytes:
    """Build a synthetic noisy colour scanned PDF that renders >3 MiB/page at 1.6x RGB."""
    import fitz

    doc = fitz.open()
    try:
        pix = fitz.Pixmap(fitz.csRGB, width, height, os.urandom(width * height * 3), False)
        img_bytes = pix.tobytes("ppm")
        del pix
        for index in range(page_count):
            page = doc.new_page(width=595, height=842)
            page.insert_image(page.rect, stream=img_bytes)
            page.insert_text((36, 36), f"Scanned statement page {index + 1}")
        return doc.tobytes(deflate=False)
    finally:
        doc.close()
        fitz.TOOLS.store_shrink(100)


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

    def test_lazy_batch_sequence_supports_indexing_slicing_and_compact_downscale(self, monkeypatch):
        service = ExtractionService()
        batches = service._render_pdf_pages_as_image_payload_batches(_pdf_with_pages(7))

        assert len(batches) == 2
        assert len(batches[0]) == 5
        # Repeated access to the same index uses the single-batch cache; pop_batch consumes it.
        assert batches[0] is batches[0]
        assert len(batches.pop_batch(0)) == 5
        assert len(batches[-1]) == 2
        assert [len(b) for b in batches[:2]] == [5, 2]
        with pytest.raises(IndexError):
            _ = batches[2]
        with pytest.raises(IndexError):
            batches.pop_batch(-3)

        # Force second-stage compact downscale when grayscale at 1.0x still exceeds the per-page cap.
        monkeypatch.setattr(service, "PDF_VISION_MAX_PAGE_IMAGE_BYTES", 80_000)
        compact_batches = service._render_pdf_pages_as_image_payload_batches(
            _scanned_pdf_with_pages(1, width=320, height=420)
        )
        assert len(compact_batches[0]) == 1


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
                "closing_balance": "175.00",
            },
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

        with patch.object(service, "_extract_json_with_model", mock_extract):
            merged = await service.extract_financial_data(pdf_bytes, "DBS", "pdf")

        assert mock_extract.await_count == 4
        meta_content = mock_extract.await_args_list[0].kwargs["messages"][0]["content"]
        assert "STAGE 1 — DOCUMENT METADATA" in meta_content[0]["text"]
        assert len(meta_content[1:]) == 10
        first_page_payload = None
        for index, call in enumerate(mock_extract.await_args_list[1:], start=1):
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
        with patch.object(service, "_extract_json_with_model", mock_extract):
            await service.extract_financial_data(_pdf_with_pages(2), "DBS", "pdf")

        assert mock_extract.await_count == 1
        text = mock_extract.await_args.kwargs["messages"][0]["content"][0]["text"]
        assert "PARTIAL DOCUMENT" not in text

    async def test_AC_extraction_2595_1_thirty_page_scanned_pdf_parse_bounds_peak_memory(self, monkeypatch):
        """AC-extraction.2595.1: parsing a 30-page noisy scanned PDF renders one
        batch on demand, downscales oversized scan pages, releases completed
        batch payloads before rendering the next batch, and keeps Python traced
        peak allocation below 32 MiB (#2595)."""
        from src.config import settings

        monkeypatch.setattr(settings, "ai_provider", "zai")
        service = ExtractionService()
        service.api_key = "test-key"

        pdf_bytes = _scanned_pdf_with_pages(30)
        gc.collect()

        live_payload_counts: list[int] = []
        active_calls = 0
        max_concurrent_calls = 0

        async def _fake_extract_json_with_model(*, messages, **kwargs):
            nonlocal active_calls, max_concurrent_calls
            active_calls += 1
            max_concurrent_calls = max(max_concurrent_calls, active_calls)
            try:
                gc.collect()
                live_payloads = [
                    obj
                    for obj in gc.get_objects()
                    if isinstance(obj, dict)
                    and obj.get("type") == "image_url"
                    and isinstance(obj.get("image_url"), dict)
                    and str(obj["image_url"].get("url", "")).startswith("data:image/png;base64,")
                ]
                live_payload_counts.append(len(live_payloads))
                return {"institution": "DBS", "transactions": [{"description": "row"}]}
            finally:
                active_calls -= 1

        tracemalloc.start()
        try:
            with patch.object(service, "_extract_json_with_model", new=_fake_extract_json_with_model):
                merged = await service.extract_financial_data(pdf_bytes, "DBS", "pdf")
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        gc.collect()
        assert max_concurrent_calls == 1
        assert len(merged["transactions"]) == 6
        # Stage 1 meta holds 5 head + 5 tail = 10 page payloads; Stage 2 batch 1 holds 5; continuation batches hold 1 context + 5 = 6.
        assert live_payload_counts == [10, 5, 6, 6, 6, 6, 6], f"Unexpected live payload counts: {live_payload_counts}"
        # Measured peak traced memory is ~6.4 MiB (vs ~250+ MiB before #2595).
        assert peak_bytes < 32 * 1024 * 1024, f"Peak traced memory {peak_bytes} B exceeded 32 MiB bound"

    async def test_AC_extraction_2595_2_total_rendered_byte_ceiling_raises_explicit_error(self, monkeypatch):
        """AC-extraction.2595.2: when cumulative rendered page PNG bytes exceed
        PDF_VISION_MAX_TOTAL_IMAGE_BYTES, extraction raises an explicit
        ExtractionError naming the byte limit before exhausting memory (#2595)."""
        from src.config import settings

        monkeypatch.setattr(settings, "ai_provider", "zai")
        service = ExtractionService()
        service.api_key = "test-key"
        monkeypatch.setattr(service, "PDF_VISION_MAX_TOTAL_IMAGE_BYTES", 4_000)

        pdf_bytes = _scanned_pdf_with_pages(3, width=400, height=400)
        mock_extract = AsyncMock(return_value={"transactions": []})

        with (
            patch.object(service, "_extract_json_with_model", mock_extract),
            pytest.raises(ExtractionError, match=r"4,000 bytes|4000 bytes"),
        ):
            await service.extract_financial_data(pdf_bytes, "DBS", "pdf")

        assert mock_extract.await_count == 0


async def test_AC_extraction_2813_1_staged_head_tail_meta_and_body_batches(monkeypatch):
    """AC-extraction.2813.1: multi-page PDFs (> 5 pages) run Stage 1 head+tail
    metadata extraction on the deduplicated first 5 + last 5 pages followed by
    Stage 2 body batch extraction, while small PDFs (<= 5 pages) extract in a
    single shot (#2813)."""
    from src.config import settings
    from src.extraction.base.paged_extraction import build_paged_meta_prompt

    monkeypatch.setattr(settings, "ai_provider", "zai")
    service = ExtractionService()
    service.api_key = "test-key"

    # 1. Small PDF (3 pages <= 5): single-shot extraction (1 model call).
    small_mock = AsyncMock(return_value={"institution": "DBS", "transactions": [{"description": "small"}]})
    with patch.object(service, "_extract_json_with_model", small_mock):
        small_res = await service.extract_financial_data(_pdf_with_pages(3), "DBS", "pdf")
    assert small_mock.await_count == 1
    assert small_res["transactions"] == [{"description": "small"}]

    # 2. Large PDF (12 pages > 5): Stage 1 (head pages 1..5 + tail pages 8..12 = 10 pages)
    #    followed by Stage 2 (3 body batches: 1..5, 6..10, 11..12).
    pdf_bytes = _pdf_with_pages(12)
    batches_ref = list(service._render_pdf_pages_as_image_payload_batches(pdf_bytes))
    all_pages = [p for b in batches_ref for p in b]
    expected_head_tail = [*all_pages[:5], *all_pages[7:12]]  # pages 1..5 and 8..12 (10 pages)

    call_payloads = [
        # Stage 1 metadata call (sees head + tail together, including final-page Balance Carried Forward)
        {
            "institution": "DBS POSB",
            "account_last4": "8123",
            "currency": "SGD",
            "period_start": "2024-11-01",
            "period_end": "2024-11-30",
            "opening_balance": "124781.91",
            "closing_balance": "133583.07",
            "transactions": [],
        },
        # Stage 2 body batches 1..3
        {"transactions": [{"description": "batch-1-txn"}]},
        {"transactions": [{"description": "batch-2-txn"}]},
        {"transactions": [{"description": "batch-3-txn"}]},
    ]
    large_mock = AsyncMock(side_effect=call_payloads)
    with patch.object(service, "_extract_json_with_model", large_mock):
        merged = await service.extract_financial_data(pdf_bytes, "DBS", "pdf")

    assert large_mock.await_count == 4
    # Verify Stage 1 metadata call received head (1-5) + tail (8-12) = 10 pages and metadata prompt
    meta_call_content = large_mock.await_args_list[0].kwargs["messages"][0]["content"]
    meta_prompt_text = meta_call_content[0]["text"]
    meta_images = meta_call_content[1:]
    assert "STAGE 1 — DOCUMENT METADATA" in meta_prompt_text
    assert "Balance Carried Forward" in meta_prompt_text
    assert len(meta_images) == 10
    assert meta_images == expected_head_tail

    # Verify build_paged_meta_prompt directly
    direct_meta_prompt = build_paged_meta_prompt("BASE", page_numbers=[1, 2, 3, 4, 5, 8, 9, 10, 11, 12], total_pages=12)
    assert "pages 1, 2, 3, 4, 5, 8, 9, 10, 11, 12 of a 12-page statement" in direct_meta_prompt

    # Verify merged result preserves Stage 1 metadata and all Stage 2 transactions in order
    assert merged["institution"] == "DBS POSB"
    assert merged["account_last4"] == "8123"
    assert merged["currency"] == "SGD"
    assert merged["period_start"] == "2024-11-01"
    assert merged["period_end"] == "2024-11-30"
    assert merged["opening_balance"] == "124781.91"
    assert merged["closing_balance"] == "133583.07"
    assert [t["description"] for t in merged["transactions"]] == [
        "batch-1-txn",
        "batch-2-txn",
        "batch-3-txn",
    ]
