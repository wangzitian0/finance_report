"""A document with several accounts is split by the row parts of each account (#2983)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import fitz
import pytest

from src.extraction.base.paged_extraction import split_paged_extractions_by_account
from src.extraction.extension.service import ExtractionService

META = {
    "institution": "Two Account Bank",
    "account_last4": "1111",
    "currency": "EUR",
    "period_start": "2026-05-01",
    "period_end": "2026-05-31",
    "opening_balance": "100.00",
    "closing_balance": "403.12",
}
FIRST_ACCOUNT = {
    "account_last4": "1111",
    "opening_balance": "100.00",
    "closing_balance": "238.52",
    "transactions": [{"description": "a1", "amount": "138.52", "direction": "IN"}],
}
SECOND_ACCOUNT = {
    "account_last4": "2222",
    "opening_balance": "200.00",
    "closing_balance": "403.12",
    "transactions": [{"description": "b1", "amount": "203.12", "direction": "IN"}],
}


@pytest.mark.no_db
def test_AC_extraction_2983_7_each_account_keeps_its_own_closing_balance():
    """AC-extraction.2983.7: a metadata part with an account suffix gives no balance to any account."""
    continuation = {"transactions": [{"description": "b2", "amount": "1.00", "direction": "OUT"}]}
    accounts = split_paged_extractions_by_account([FIRST_ACCOUNT, SECOND_ACCOUNT, continuation], metadata=META)
    assert [
        (a["account_last4"], a["opening_balance"], a["closing_balance"], [t["description"] for t in a["transactions"]])
        for a in accounts
    ] == [("1111", "100.00", "238.52", ["a1"]), ("2222", "200.00", "403.12", ["b1", "b2"])]
    assert all(
        (a["institution"], a["period_start"], a["period_end"]) == ("Two Account Bank", "2026-05-01", "2026-05-31")
        for a in accounts
    )

    no_printed_balance = {k: v for k, v in FIRST_ACCOUNT.items() if k not in ("opening_balance", "closing_balance")}
    first, _second = split_paged_extractions_by_account([no_printed_balance, SECOND_ACCOUNT], metadata=META)
    assert first.get("opening_balance") is None and first.get("closing_balance") is None

    leading = {"transactions": [{"description": "a0", "amount": "2.00", "direction": "IN"}]}
    first, _second = split_paged_extractions_by_account([leading, FIRST_ACCOUNT, SECOND_ACCOUNT], metadata=META)
    assert [t["description"] for t in first["transactions"]] == ["a0", "a1"]


@pytest.mark.no_db
def test_AC_extraction_2983_8_metadata_suffix_alone_is_not_an_account():
    """AC-extraction.2983.8: row parts of one account give one account, without the balances of the metadata part."""
    rows_only = {k: v for k, v in SECOND_ACCOUNT.items() if k not in ("opening_balance", "closing_balance")}
    accounts = split_paged_extractions_by_account([rows_only], metadata=META)
    assert len(accounts) == 1
    only = accounts[0]
    assert only["account_last4"] == "2222" and only["institution"] == "Two Account Bank"
    assert only.get("opening_balance") is None and only.get("closing_balance") is None
    assert [t["description"] for t in only["transactions"]] == ["b1"]


def _image_batches(*_args, **_kwargs):
    return [[{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]]


@pytest.mark.no_db
async def test_AC_extraction_2983_9_single_batch_account_conflict_is_split_in_the_first_pass():
    """AC-extraction.2983.9: a metadata reply and a rows reply with two suffixes end in pass 1, without a third call."""
    service = ExtractionService()
    service.api_key, service.multimodal_model = "test-key", "test-model"
    model_call = AsyncMock(side_effect=[dict(META), dict(SECOND_ACCOUNT)])
    with (
        patch.object(service, "_extract_json_with_model", model_call),
        patch.object(service, "_build_vision_media_payload_batches", _image_batches),
    ):
        slices, split_meta_agreed = await service._extract_with_balance_retry(
            file_content=b"png", institution=None, file_type="png", file_url=None, force_model=None, filename="s.png"
        )
    assert model_call.await_count == 2
    assert split_meta_agreed is False and len(slices) == 1
    payload = slices[0].payload
    assert payload["account_last4"] == "2222" and payload["institution"] == "Two Account Bank"
    assert payload.get("opening_balance") is None and payload.get("closing_balance") is None
    assert [t["description"] for t in payload["transactions"]] == ["b1"]


def _text_pdf(page_count: int) -> bytes:
    doc = fitz.open()
    for index in range(page_count):
        doc.new_page().insert_text((72, 72), f"{index + 1} Jan PAYMENT {index + 1}0.00 CR")
    data = doc.tobytes()
    doc.close()
    return data


@pytest.mark.no_db
async def test_AC_extraction_2983_10_text_split_by_account_does_not_fall_back_to_images():
    """AC-extraction.2983.10: an account split read from the text layer is the result; no image call follows."""
    service = ExtractionService()
    service.api_key, service.multimodal_model = "test-key", "test-model"
    model_call = AsyncMock(side_effect=[dict(META), dict(FIRST_ACCOUNT), dict(SECOND_ACCOUNT)])
    images = AsyncMock(side_effect=AssertionError("the image path must not run"))
    with (
        patch.object(service, "_extract_json_with_model", model_call),
        patch.object(service, "_build_vision_media_payload_batches", images),
    ):
        extracted = await service.extract_financial_data(_text_pdf(service.PDF_VISION_MAX_PAGES + 2), None, "pdf")
    assert model_call.await_count == 3
    assert [(a["account_last4"], a["closing_balance"]) for a in extracted["accounts"]] == [
        ("1111", "238.52"),
        ("2222", "403.12"),
    ]
