from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.models.statement import BankStatementStatus, ConfidenceLevel
from src.services.extraction import ExtractionError, ExtractionService


async def mock_stream_generator(content: str):
    """Helper to create async generator for streaming mock."""
    yield content


@pytest.mark.asyncio
async def test_parse_document_csv_no_content():
    service = ExtractionService()
    with pytest.raises(ExtractionError, match="File content is required for CSV parsing"):
        await service.parse_document(
            file_path=Path("test.csv"),
            institution="DBS",
            user_id=uuid4(),
            file_type="csv",
            file_content=None,
        )


@pytest.mark.asyncio
async def test_parse_document_unsupported_type():
    service = ExtractionService()
    with pytest.raises(ExtractionError, match="Unsupported file type: exe"):
        await service.parse_document(
            file_path=Path("test.exe"),
            institution="DBS",
            user_id=uuid4(),
            file_type="exe",
            file_content=b"content",
        )


def test_safe_date_invalid():
    service = ExtractionService()
    with pytest.raises(ValueError, match="Invalid date format"):
        service._safe_date("not-a-date")


@pytest.mark.asyncio
async def test_extract_financial_data_no_content_no_url():
    service = ExtractionService()
    with pytest.raises(ExtractionError, match="File content is required"):
        await service.extract_financial_data(None, "DBS", "pdf")


@pytest.mark.asyncio
async def test_extract_financial_data_no_api_key(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "openrouter_api_key", "")
    service = ExtractionService()
    with pytest.raises(ExtractionError, match="OpenRouter API key not configured"):
        await service.extract_financial_data(b"content", "DBS", "pdf")


@pytest.mark.asyncio
async def test_extract_financial_data_all_models_fail():
    service = ExtractionService()
    service.api_key = "test-key"

    from src.services.openrouter_streaming import OpenRouterStreamError

    with patch("src.services.extraction.stream_openrouter_json") as mock_stream:
        mock_stream.side_effect = OpenRouterStreamError("HTTP 429: Quota Exceeded")

        with pytest.raises(ExtractionError, match="rate limited"):
            await service.extract_financial_data(b"content", "DBS", "pdf")


@pytest.mark.asyncio
async def test_extract_financial_data_json_markdown_fallback():
    service = ExtractionService()
    service.api_key = "test-key"

    content = 'Here is the data: ```json\n{"account_last4": "1234"}\n```'

    with patch("src.services.extraction.stream_openrouter_json") as mock_stream:
        mock_stream.return_value = mock_stream_generator(content)

        result = await service.extract_financial_data(b"content", "DBS", "pdf")
        assert result["account_last4"] == "1234"


@pytest.mark.asyncio
async def test_extract_financial_data_invalid_json_all_attempts():
    service = ExtractionService()
    service.api_key = "test-key"

    content = "Invalid JSON without markdown that is clearly not empty"

    with patch("src.services.extraction.stream_openrouter_json") as mock_stream:
        mock_stream.return_value = mock_stream_generator(content)

        with pytest.raises(ExtractionError, match=r"All \d+ models failed\. Breakdown:.*"):
            await service.extract_financial_data(b"content", "DBS", "pdf")


@pytest.mark.asyncio
async def test_parse_document_with_transaction_missing_fields():
    service = ExtractionService()
    # Mock extract_financial_data to return a transaction with missing date
    service.extract_financial_data = AsyncMock(
        return_value={
            "period_start": "2023-01-01",
            "period_end": "2023-01-31",
            "opening_balance": "100.00",
            "closing_balance": "150.00",
            "transactions": [
                {"amount": "50.00", "direction": "IN", "description": "No date"},
                {
                    "date": "2023-01-15",
                    "amount": "50.00",
                    "direction": "IN",
                    "description": "Valid",
                },
            ],
        }
    )

    statement, transactions = await service.parse_document(
        file_path=Path("test.pdf"), institution="DBS", user_id=uuid4(), file_content=b"content"
    )
    # The first transaction should be skipped because it lacks a date
    assert len(transactions) == 1
    assert transactions[0].description == "Valid"


@pytest.mark.asyncio
async def test_parse_document_with_invalid_date_formats():
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "period_start": "2023-01-01",
            "period_end": "2023-01-31",
            "opening_balance": "100.00",
            "closing_balance": "150.00",
            "transactions": [
                {
                    "date": "invalid-date",
                    "amount": "50.00",
                    "direction": "IN",
                    "description": "Bad date",
                },
                {
                    "date": "None",
                    "amount": "50.00",
                    "direction": "IN",
                    "description": "None string",
                },
            ],
        }
    )

    statement, transactions = await service.parse_document(
        file_path=Path("test.pdf"), institution="DBS", user_id=uuid4(), file_content=b"content"
    )
    # Both transactions have invalid dates and should be skipped
    assert len(transactions) == 0


@pytest.mark.asyncio
async def test_parse_document_unexpected_exception():
    service = ExtractionService()
    # Force an unexpected exception by mocking extract_financial_data to raise one
    service.extract_financial_data = AsyncMock(side_effect=RuntimeError("Boom"))

    with pytest.raises(ExtractionError, match="Failed to parse document: Boom"):
        await service.parse_document(
            file_path=Path("test.pdf"), institution="DBS", user_id=uuid4(), file_content=b"content"
        )


def test_safe_decimal_invalid():
    service = ExtractionService()
    # Test invalid string conversion
    assert service._safe_decimal("not-a-number", default="1.23") == Decimal("1.23")
    # Test None value
    assert service._safe_decimal(None, default="0.00") == Decimal("0.00")


def test_compute_event_confidence_missing_fields():
    service = ExtractionService()
    # Missing 'direction'
    txn = {"date": "2023-01-01", "description": "test", "amount": "10.00"}
    assert service._compute_event_confidence(txn) == ConfidenceLevel.LOW

    # Invalid date format
    txn = {"date": "bad", "description": "test", "amount": "10.00", "direction": "IN"}
    assert service._compute_event_confidence(txn) == ConfidenceLevel.LOW


def test_validate_external_url_invalid_cases():
    service = ExtractionService()
    # Missing hostname
    assert service._validate_external_url("http:///path") is False
    # Localhost
    assert service._validate_external_url("http://localhost:8000") is False
    # Private IP
    assert service._validate_external_url("http://192.168.1.1") is False
    # Internal Docker name (no dots)
    assert service._validate_external_url("http://minio:9000") is False
    # Valid URL
    assert service._validate_external_url("https://google.com") is True
    # malformed URL
    assert service._validate_external_url("not a url") is False


@pytest.mark.asyncio
async def test_handle_parse_failure(db):
    from src.models import BankStatement
    from src.routers.statements import _handle_parse_failure

    sid = uuid4()
    statement = BankStatement(
        id=sid,
        user_id=uuid4(),
        status=BankStatementStatus.PARSING,
        file_path="p",
        file_hash="h_fail",
        original_filename="f.pdf",
        institution="DBS",
    )
    db.add(statement)
    await db.commit()

    await _handle_parse_failure(statement, db, message="Something went wrong")

    await db.refresh(statement)
    assert statement.status == BankStatementStatus.REJECTED
    assert statement.validation_error == "Something went wrong"
    assert statement.confidence_score == 0


@pytest.mark.asyncio
async def test_parse_statement_background_storage_error(db, monkeypatch):
    from src.database import create_session_maker_from_db
    from src.models import BankStatement
    from src.routers.statements import _parse_statement_background
    from src.services.storage import StorageError

    sid = uuid4()
    uid = uuid4()
    statement = BankStatement(
        id=sid,
        user_id=uid,
        status=BankStatementStatus.PARSING,
        file_path="p",
        file_hash="h_storage_err",
        original_filename="f.pdf",
        institution="DBS",
    )
    db.add(statement)
    await db.commit()

    async def mock_run_in_threadpool(func, *args, **kwargs):
        if "generate_presigned_url" in str(func):
            raise StorageError("Presigned fail")
        return func(*args, **kwargs)

    monkeypatch.setattr("src.routers.statements.run_in_threadpool", mock_run_in_threadpool)

    await _parse_statement_background(
        statement_id=sid,
        filename="f.pdf",
        institution="DBS",
        user_id=uid,
        account_id=None,
        file_hash="h_storage_err",
        storage_key="p",
        content=b"content",
        model=None,
        session_maker=create_session_maker_from_db(db),
    )

    await db.refresh(statement)
    # After PR #117: Presigned URL failure is logged but doesn't stop processing.
    # Processing continues with base64 fallback, then fails at extraction.
    assert statement.status == BankStatementStatus.REJECTED
    assert statement.validation_error is not None
    # Flexible check for failure reason
    error_msg = statement.validation_error.lower()
    assert any(term in error_msg for term in ["failed", "not configured", "no valid file"])
