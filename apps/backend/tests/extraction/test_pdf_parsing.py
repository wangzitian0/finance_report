from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import UploadFile

import src.routers.statements
from src.extraction import DocumentSource
from src.extraction.base.validation import evaluate_statement_balance, validate_completeness
from src.extraction.extension.service import ExtractionError, ExtractionService
from pydantic_ai.exceptions import ModelHTTPError, ModelTimeoutError
from tests._support.fake_llm import install_fake_model


def make_upload_file(name: str, content: bytes) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(content))


async def test_invalid_parse_not_persisted_and_balance_validation(tmp_path):
    service = ExtractionService()
    bad_file = tmp_path / "bad.pdf"
    bad_file.write_bytes(b"not a valid pdf")
    with (
        patch.object(
            service,
            "extract_financial_data",
            new_callable=AsyncMock,
            side_effect=ExtractionError("Failed to parse document"),
        ),
        pytest.raises(ExtractionError, match="Failed to parse"),
    ):
        await service.parse_document(
            DocumentSource.resolve(path=bad_file, content=bad_file.read_bytes()), "DBS", user_id=uuid4()
        )

    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(b"dummy")
    mock_data = {
        "institution": "DBS",
        "account_last4": "1234",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "1000.00",
        "closing_balance": "2000.00",
        "transactions": [{"date": "2025-01-15", "description": "Test", "amount": "100.00", "direction": "IN"}],
    }
    with patch.object(service, "extract_financial_data", new_callable=AsyncMock, return_value=mock_data):
        result = await service.parse_document(
            DocumentSource.resolve(path=pdf_file, content=pdf_file.read_bytes()), "DBS", user_id=uuid4()
        )
    assert (
        result.balance_validated is False
        and result.review_reasons
        and "llm_led_balance_chain_unreconciled" in result.review_reasons[0]
    )

    val = evaluate_statement_balance(
        opening=Decimal("100.00"),
        closing=Decimal("500.00"),
        currency=None,
        currency_balances=None,
        transactions=[{"amount": "50.00", "direction": "IN"}],
    )
    assert val["balance_valid"] is False and (
        "mismatch" in val.get("notes", "").lower() or Decimal(val["difference"]) > Decimal("0.1")
    )


async def test_upload_file_size_limit(client, monkeypatch):
    monkeypatch.setattr(src.routers.statements, "MAX_UPLOAD_BYTES", 1024)
    too_big = await client.post(
        "/statements",
        files={"file": ("large.pdf", BytesIO(b"x" * 1025), "application/pdf")},
        data={"institution": "DBS"},
    )
    assert too_big.status_code == 413 and "10MB" in too_big.json().get("detail", "")

    monkeypatch.setattr("src.routers.statements.StorageService", MagicMock(return_value=MagicMock()))

    async def fake_parse(*args, **kwargs):
        raise ExtractionError("test-only extraction bypass")

    monkeypatch.setattr(ExtractionService, "parse_documents", fake_parse)
    at_limit = await client.post(
        "/statements",
        files={"file": ("exact.pdf", BytesIO(b"x" * 1024), "application/pdf")},
        data={"institution": "DBS"},
    )
    assert at_limit.status_code != 413


async def test_parsing_stream_errors_and_api_key_guard(monkeypatch):
    service = ExtractionService()
    service.api_key = None
    with pytest.raises(ExtractionError, match="API key not configured"):
        await service.extract_financial_data(b"content", "DBS", "png")

    service.api_key = "test-key"
    for err, match in [
        (ModelTimeoutError("m", "Connection timed out"), "timeout"),
        (ModelHTTPError(status_code=429, model_name="m", body="Rate limit exceeded"), "429"),
    ]:

        def fail(_content, err=err):
            raise err

        install_fake_model(monkeypatch, fail)
        with pytest.raises(ExtractionError, match=match):
            await service.extract_financial_data(b"content", "DBS", "pdf", file_url="https://example.com/file.pdf")


def test_statement_completeness():
    missing = validate_completeness({"institution": "DBS", "period_start": "2025-01-01"})
    complete = {
        "institution": "DBS",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "100.00",
        "closing_balance": "150.00",
        "transactions": [{"amount": "50.00", "direction": "IN"}],
    }
    assert {"period_end", "opening_balance", "closing_balance"} <= set(missing) and validate_completeness(
        complete
    ) == []
