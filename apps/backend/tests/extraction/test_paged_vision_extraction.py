from __future__ import annotations

import gc
import os
import tracemalloc
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest

from src.config import settings
from src.extraction.base.paged_extraction import build_paged_meta_prompt, build_paged_prompt, merge_paged_extractions
from src.extraction.extension._base import ExtractionError
from src.extraction.extension.service import ExtractionService


def _pdf_with_pages(page_count: int) -> bytes:
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    pdf = canvas.Canvas(buf)
    for index in range(page_count):
        pdf.drawString(72, 720, f"statement fixture page {index + 1}")
        pdf.showPage()
    pdf.save()
    return buf.getvalue()


def _scanned_pdf(page_count: int, *, width: int = 520, height: int = 700) -> bytes:
    import fitz

    doc = fitz.open()
    try:
        pix = fitz.Pixmap(fitz.csRGB, width, height, os.urandom(width * height * 3), False)
        img = pix.tobytes("ppm")
        del pix
        for index in range(page_count):
            page = doc.new_page(width=595, height=842)
            page.insert_image(page.rect, stream=img)
            page.insert_text((36, 36), f"Scanned statement page {index + 1}")
        return doc.tobytes(deflate=False)
    finally:
        doc.close()
        fitz.TOOLS.store_shrink(100)


def test_render_all_pages_in_batches_and_lazy_sequence(monkeypatch):
    service = ExtractionService()
    batches = service._render_pdf_pages_as_image_payload_batches(_pdf_with_pages(service.PDF_VISION_MAX_PAGES * 2 + 2))
    rendered = [p for b in batches for p in b]
    assert (
        [len(b) for b in batches] == [5, 5, 2]
        and len(rendered) == 12
        and all(p["image_url"]["url"].startswith("data:image/png;base64,") for p in rendered)
    )

    oversize = service.PDF_VISION_MAX_TOTAL_PAGES + 1
    with pytest.raises(ExtractionError, match=f"{oversize} pages.*{service.PDF_VISION_MAX_TOTAL_PAGES}-page"):
        service._render_pdf_pages_as_image_payload_batches(_pdf_with_pages(oversize))

    lazy = service._render_pdf_pages_as_image_payload_batches(_pdf_with_pages(7))
    assert (
        len(lazy),
        len(lazy[0]),
        lazy[0] is lazy[0],
        len(lazy.pop_batch(0)),
        len(lazy[-1]),
        [len(b) for b in lazy[:2]],
    ) == (2, 5, True, 5, 2, [5, 2])
    for op in (lambda: lazy[2], lambda: lazy.pop_batch(-3)):
        with pytest.raises(IndexError):
            op()
    monkeypatch.setattr(service, "PDF_VISION_MAX_PAGE_IMAGE_BYTES", 80000)
    assert len(service._render_pdf_pages_as_image_payload_batches(_scanned_pdf(1, width=320, height=420))[0]) == 1


def test_merge_and_prompt_paged_extractions():
    merged = merge_paged_extractions(
        [
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
    )
    assert (
        merged["institution"],
        merged["account_last4"],
        merged["currency"],
        merged["opening_balance"],
        merged["closing_balance"],
        [t["description"] for t in merged["transactions"]],
    ) == ("DBS", "0355", "SGD", "100.00", "175.00", ["t1", "t2", "t3", "t4"])
    assert [
        p["symbol"]
        for p in merge_paged_extractions(
            [
                {"positions": [{"symbol": "A"}], "transactions": []},
                {"positions": [{"symbol": "B"}, {"symbol": "C"}], "transactions": []},
            ]
        )["positions"]
    ] == ["A", "B", "C"]
    single = {"institution": "GXS", "transactions": [{"description": "t1"}]}
    assert merge_paged_extractions([single]) is single
    with pytest.raises(ValueError):
        merge_paged_extractions([])

    assert build_paged_prompt("BASE", part_index=1, part_count=1, page_start=1, page_end=5, total_pages=5) == "BASE"
    p_plain, p_ctx, p_first = (
        build_paged_prompt("BASE", part_index=2, part_count=3, page_start=6, page_end=10, total_pages=12),
        build_paged_prompt(
            "BASE", part_index=2, part_count=3, page_start=6, page_end=10, total_pages=12, has_context_page=True
        ),
        build_paged_prompt("BASE", part_index=1, part_count=3, page_start=1, page_end=5, total_pages=12),
    )
    assert p_plain.startswith("BASE") and all(
        s in p_plain for s in ("pages 6-10", "12-page", "(2/3)", "balance-carried-forward")
    )
    assert (
        "ONLY as context" in p_ctx
        and "Do NOT extract transactions from this context page" in p_ctx
        and "only pages 6-10" not in p_ctx
        and "the FIRST page below is" in p_ctx
        and "context page" not in p_first
    )
    assert "pages 1, 2, 3, 4, 5, 8, 9, 10, 11, 12 of a 12-page statement" in build_paged_meta_prompt(
        "BASE", page_numbers=[1, 2, 3, 4, 5, 8, 9, 10, 11, 12], total_pages=12
    )


async def test_batched_extract_flows_and_staged_meta(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "zai")
    service = ExtractionService()
    service.api_key = "test-key"

    pdf_bytes = _pdf_with_pages(service.PDF_VISION_MAX_PAGES * 2 + 2)
    mock_extract = AsyncMock(
        side_effect=[
            {"institution": "DBS", "currency": "SGD", "opening_balance": "100.00", "closing_balance": "175.00"},
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
    )
    with patch.object(service, "_extract_json_with_model", mock_extract):
        merged = await service.extract_financial_data(pdf_bytes, "DBS", "pdf")
    calls = mock_extract.await_args_list
    meta_content, first_page = calls[0].kwargs["messages"][0]["content"], calls[1].kwargs["messages"][0]["content"][1]
    assert (
        mock_extract.await_count == 4
        and "STAGE 1 — DOCUMENT METADATA" in meta_content[0]["text"]
        and "Balance Carried Forward" in meta_content[0]["text"]
        and len(meta_content[1:]) == 10
    )
    all_pages = [p for b in list(service._render_pdf_pages_as_image_payload_batches(pdf_bytes)) for p in b]
    assert meta_content[1:] == [*all_pages[:5], *all_pages[7:12]]
    assert all(
        f"({i}/3)" in c.kwargs["messages"][0]["content"][0]["text"]
        and (
            len(c.kwargs["messages"][0]["content"][1:]) == 5
            and "context page" not in c.kwargs["messages"][0]["content"][0]["text"]
            if i == 1
            else len(c.kwargs["messages"][0]["content"][1:]) == (6 if i < 3 else 3)
            and c.kwargs["messages"][0]["content"][1] == first_page
            and "Do NOT extract transactions from this context page" in c.kwargs["messages"][0]["content"][0]["text"]
        )
        for i, c in enumerate(calls[1:], start=1)
    )
    assert (
        merged["institution"],
        merged["opening_balance"],
        merged["closing_balance"],
        [t["description"] for t in merged["transactions"]],
    ) == ("DBS", "100.00", "175.00", ["t1", "t2", "t3"])

    for pages in (2, 3):
        single = AsyncMock(return_value={"institution": "DBS", "transactions": [{"description": "small"}]})
        with patch.object(service, "_extract_json_with_model", single):
            res = await service.extract_financial_data(_pdf_with_pages(pages), "DBS", "pdf")
        assert (
            single.await_count == 2
            and all(
                "PARTIAL DOCUMENT" not in c.kwargs["messages"][0]["content"][0]["text"] for c in single.await_args_list
            )
            and res["transactions"] == [{"description": "small"}]
        )


async def test_AC_extraction_2595_memory_and_byte_ceiling(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "zai")
    service = ExtractionService()
    service.api_key = "test-key"
    pdf_bytes = _scanned_pdf(30)
    gc.collect()
    live_counts, active, max_active = [], 0, 0

    async def fake_extract(*, messages, **_kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        try:
            live_counts.append(
                sum(
                    1
                    for o in messages[0]["content"]
                    if isinstance(o, dict)
                    and o.get("type") == "image_url"
                    and str((o.get("image_url") or {}).get("url", "")).startswith("data:image/png;base64,")
                )
            )
            return {"institution": "DBS", "transactions": [{"description": "row"}]}
        finally:
            active -= 1

    tracemalloc.start()
    try:
        with patch.object(service, "_extract_json_with_model", new=fake_extract):
            merged = await service.extract_financial_data(pdf_bytes, "DBS", "pdf")
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    gc.collect()
    assert (max_active, len(merged["transactions"]), live_counts) == (
        1,
        6,
        [10, 5, 6, 6, 6, 6, 6],
    ) and peak_bytes < 32 * 1024 * 1024

    monkeypatch.setattr(service, "PDF_VISION_MAX_TOTAL_IMAGE_BYTES", 4000)
    blocked = AsyncMock(return_value={"transactions": []})
    with (
        patch.object(service, "_extract_json_with_model", blocked),
        pytest.raises(ExtractionError, match="4,000 bytes|4000 bytes"),
    ):
        await service.extract_financial_data(_scanned_pdf(3, width=400, height=400), "DBS", "pdf")
    assert blocked.await_count == 0


def test_consolidated_brokerage_allows_multiple_subaccounts_while_bank_still_rejects():
    from src.extraction.base.paged_extraction import MultipleAccountsError

    parts = [
        {
            "institution": "Fidelity",
            "account_last4": "Z401",
            "currency": "USD",
            "positions": [{"symbol": "SPY", "quantity": "5", "market_value": "2500.00", "currency": "USD"}],
        },
        {
            "institution": "Fidelity",
            "account_last4": "2252",
            "currency": "USD",
            "positions": [{"symbol": "QQQ", "quantity": "2", "market_value": "1000.00", "currency": "USD"}],
        },
    ]
    with pytest.raises(MultipleAccountsError):
        merge_paged_extractions(parts)
    merged = merge_paged_extractions(parts, allow_multiple_accounts=True)
    assert merged["account_last4"] == "Z401"
    assert [p["symbol"] for p in merged["positions"]] == ["SPY", "QQQ"]


def test_a_page_that_mupdf_cannot_draw_is_an_extraction_error_not_a_bare_runtime_error(monkeypatch):
    """Review of #3202: the retry loop keeps an earlier pass for an `ExtractionError` only."""
    import fitz

    service = ExtractionService()
    document = fitz.open(stream=_pdf_with_pages(1), filetype="pdf")
    try:
        page = document.load_page(0)
        monkeypatch.setattr(type(page), "get_pixmap", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("mupdf: broken")))
        with pytest.raises(ExtractionError, match="^Failed to render page 1: RuntimeError$") as raised:
            service._render_pdf_page_image_payload(document, fitz, 0)
        assert isinstance(raised.value.__cause__, RuntimeError)
        with pytest.raises(ExtractionError, match="^Failed to render page 9: ValueError$"):
            service._render_pdf_page_image_payload(document, fitz, 8)  # a page that does not exist
    finally:
        document.close()
