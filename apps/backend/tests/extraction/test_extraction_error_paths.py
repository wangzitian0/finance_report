from datetime import date
from decimal import Decimal  # noqa: F401
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from src.models.statement import BankStatementStatus, ConfidenceLevel
from src.services.deduplication import dual_write_layer2
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
            await service.extract_financial_data(
                b"content",
                "DBS",
                "pdf",
                file_url="https://example.com/file.pdf",
            )


@pytest.mark.asyncio
async def test_extract_financial_data_json_markdown_fallback():
    service = ExtractionService()
    service.api_key = "test-key"

    # Current code rejects markdown wrapping - test that it properly rejects
    content = 'Here is data: ```json\n{"account_last4": "1234"}\n```'

    with patch("src.services.extraction.stream_openrouter_json") as mock_stream:
        mock_stream.return_value = mock_stream_generator(content)

        with pytest.raises(ExtractionError, match="strict JSON object.*no markdown"):
            await service.extract_financial_data(
                b"content",
                "DBS",
                "pdf",
                file_url="https://example.com/file.pdf",
            )


@pytest.mark.asyncio
async def test_extract_financial_data_invalid_json_all_attempts():
    service = ExtractionService()
    service.api_key = "test-key"

    # Invalid JSON - should fail with JSON parse error immediately
    content = "Invalid JSON without markdown that is clearly not empty"

    with patch("src.services.extraction.stream_openrouter_json") as mock_stream:
        mock_stream.return_value = mock_stream_generator(content)

        # Now expects JSON parse error, not "all models failed"
        with pytest.raises(ExtractionError, match="strict JSON object"):
            await service.extract_financial_data(
                b"content",
                "DBS",
                "pdf",
                file_url="https://example.com/file.pdf",
            )


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

    with pytest.raises(ExtractionError, match="Transaction missing required fields"):
        await service.parse_document(
            file_path=Path("test.pdf"), institution="DBS", user_id=uuid4(), file_content=b"content"
        )


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

    with pytest.raises(ExtractionError, match="Invalid transaction date format"):
        await service.parse_document(
            file_path=Path("test.pdf"), institution="DBS", user_id=uuid4(), file_content=b"content"
        )


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
    assert service._safe_decimal("1.23") == Decimal("1.23")
    with pytest.raises(ValueError, match="Invalid decimal value"):
        service._safe_decimal("not-a-number")
    assert service._safe_decimal(None) is None
    with pytest.raises(ValueError, match="Decimal value is required"):
        service._safe_decimal(None, required=True)


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
    from src.services.statement_parsing import handle_parse_failure

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

    await handle_parse_failure(statement, db, message="Something went wrong")

    await db.refresh(statement)
    assert statement.status == BankStatementStatus.REJECTED
    assert statement.validation_error == "Something went wrong"
    assert statement.confidence_score == 0


@pytest.mark.asyncio
async def test_parse_statement_background_storage_error(db, monkeypatch):
    from src.database import create_session_maker_from_db
    from src.models import BankStatement
    from src.services.statement_parsing import parse_statement_background
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

    monkeypatch.setattr("fastapi.concurrency.run_in_threadpool", mock_run_in_threadpool)

    mock_parse = AsyncMock(side_effect=ExtractionError("API key not configured"))
    monkeypatch.setattr("src.services.extraction.ExtractionService.parse_document", mock_parse)

    await parse_statement_background(
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
    assert statement.status == BankStatementStatus.REJECTED
    assert statement.validation_error is not None
    error_msg = statement.validation_error.lower()
    assert "api key" in error_msg or "configured" in error_msg


# ---------------------------------------------------------------------------
# _sanitize_account_last4 unit tests
# ---------------------------------------------------------------------------


class TestSanitizeAccountLast4:
    def test_strips_hyphens(self):
        result = ExtractionService._sanitize_account_last4("553-3")
        assert result == "5533"

    def test_takes_last4_when_longer(self):
        result = ExtractionService._sanitize_account_last4("XXX-553-3")
        assert result == "5533"

    def test_none_returns_none(self):
        assert ExtractionService._sanitize_account_last4(None) is None

    def test_empty_string_returns_none(self):
        assert ExtractionService._sanitize_account_last4("") is None

    def test_short_value_preserved(self):
        assert ExtractionService._sanitize_account_last4("12") == "12"

    def test_only_special_chars_returns_none(self):
        assert ExtractionService._sanitize_account_last4("---") is None

    def test_already_clean_4_digits(self):
        assert ExtractionService._sanitize_account_last4("1234") == "1234"

    def test_strips_spaces(self):
        assert ExtractionService._sanitize_account_last4("12 34") == "1234"

    def test_mixed_alpha_numeric(self):
        assert ExtractionService._sanitize_account_last4("AB-12") == "AB12"

    def test_longer_alphanumeric_takes_last4(self):
        assert ExtractionService._sanitize_account_last4("ABCDEF1234") == "1234"

    def test_unicode_stripped(self):
        assert ExtractionService._sanitize_account_last4("12号34") == "1234"

    def test_single_char(self):
        assert ExtractionService._sanitize_account_last4("A") == "A"


# ---------------------------------------------------------------------------
# _handle_parse_failure edge-case tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_parse_failure_truncates_long_message(db):
    from src.models import BankStatement
    from src.services.statement_parsing import handle_parse_failure

    sid = uuid4()
    statement = BankStatement(
        id=sid,
        user_id=uuid4(),
        status=BankStatementStatus.PARSING,
        file_path="p",
        file_hash="h_trunc",
        original_filename="f.pdf",
        institution="DBS",
    )
    db.add(statement)
    await db.commit()

    long_message = "x" * 1000
    await handle_parse_failure(statement, db, message=long_message)

    await db.refresh(statement)
    assert statement.status == BankStatementStatus.REJECTED
    assert statement.validation_error is not None
    assert len(statement.validation_error) == 500


@pytest.mark.asyncio
async def test_handle_parse_failure_after_db_error(db):
    """Handler recovers from a session with pending rollback error."""
    from sqlalchemy import text

    from src.models import BankStatement
    from src.services.statement_parsing import handle_parse_failure

    sid = uuid4()
    statement = BankStatement(
        id=sid,
        user_id=uuid4(),
        status=BankStatementStatus.PARSING,
        file_path="p",
        file_hash="h_dberr",
        original_filename="f.pdf",
        institution="DBS",
    )
    db.add(statement)
    await db.commit()

    # Put session into failed-transaction state (requires rollback before reuse)
    try:
        await db.execute(text("SELECT * FROM nonexistent_table_xyz"))
    except Exception as exc:
        assert "nonexistent_table_xyz" in str(exc)

    await handle_parse_failure(statement, db, message="DB error occurred")

    # Rollback expires all ORM objects → re-fetch via saved PK
    result = await db.get(BankStatement, sid)
    assert result is not None
    assert result.status == BankStatementStatus.REJECTED
    assert result.validation_error == "DB error occurred"
    assert result.confidence_score == 0
    assert result.balance_validated is False


@pytest.mark.asyncio
async def test_handle_parse_failure_none_message(db):
    from src.models import BankStatement
    from src.services.statement_parsing import handle_parse_failure

    sid = uuid4()
    statement = BankStatement(
        id=sid,
        user_id=uuid4(),
        status=BankStatementStatus.PARSING,
        file_path="p",
        file_hash="h_none_msg",
        original_filename="f.pdf",
        institution="DBS",
    )
    db.add(statement)
    await db.commit()

    await handle_parse_failure(statement, db, message=None)

    await db.refresh(statement)
    assert statement.status == BankStatementStatus.REJECTED
    assert statement.validation_error is None


# ---------------------------------------------------------------------------
# _safe_decimal with default parameter (line 76)
# ---------------------------------------------------------------------------


def test_safe_decimal_with_default_value():
    service = ExtractionService()
    # When value is None but default is provided, should use the default
    result = service._safe_decimal(None, default="42.50")
    assert result == Decimal("42.50")


# ---------------------------------------------------------------------------
# _validate_external_url exception catch path (lines 184-191)
# ---------------------------------------------------------------------------


def test_validate_external_url_exception_path():
    """Exercise the generic except branch in _validate_external_url (lines 184-191)."""
    service = ExtractionService()
    # Passing a non-string type (int) will make urlparse raise or behave unexpectedly
    # triggering the except Exception catch-all.
    assert service._validate_external_url(cast(str, None)) is False


# ---------------------------------------------------------------------------
# parse_document: non-string date (line 261-262), invalid date strings (265-273),
# invalid amount (282-283)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_document_non_string_date():
    """Transaction date as non-string type triggers str() conversion (lines 261-262)."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "period_start": "2023-01-01",
            "period_end": "2023-01-31",
            "opening_balance": "100.00",
            "closing_balance": "200.00",
            "transactions": [
                {
                    "date": True,  # bool, not str -> triggers str() conversion -> 'True'
                    "amount": "100.00",
                    "direction": "IN",
                    "description": "Bool date",
                },
            ],
        }
    )
    # str(True) -> 'True' which is not ISO format -> should raise
    with pytest.raises(ExtractionError, match="Invalid transaction date format"):
        await service.parse_document(
            file_path=Path("test.pdf"), institution="DBS", user_id=uuid4(), file_content=b"content"
        )


@pytest.mark.asyncio
async def test_parse_document_skips_none_date_string():
    """Date value 'None' and 'null' should be skipped, not raise (lines 265-273)."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "period_start": "2023-01-01",
            "period_end": "2023-01-31",
            "opening_balance": "100.00",
            "closing_balance": "200.00",
            "transactions": [
                {
                    "date": "None",
                    "amount": "50.00",
                    "direction": "IN",
                    "description": "None string date",
                },
                {
                    "date": "null",
                    "amount": "70.00",
                    "direction": "IN",
                    "description": "Null string date",
                },
                {
                    "date": "2023-01-15",
                    "amount": "100.00",
                    "direction": "IN",
                    "description": "Valid",
                },
            ],
        }
    )
    # 'None' and 'null' dates should be skipped, only valid one remains
    statement, transactions = await service.parse_document(
        file_path=Path("test.pdf"), institution="DBS", user_id=uuid4(), file_content=b"content"
    )
    assert len(transactions) == 1
    assert transactions[0].description == "Valid"


@pytest.mark.asyncio
async def test_parse_document_invalid_amount():
    """Invalid amount string triggers ExtractionError (lines 282-283)."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "period_start": "2023-01-01",
            "period_end": "2023-01-31",
            "opening_balance": "100.00",
            "closing_balance": "200.00",
            "transactions": [
                {
                    "date": "2023-01-15",
                    "amount": "not-a-number",
                    "direction": "IN",
                    "description": "Bad amount",
                },
            ],
        }
    )
    with pytest.raises(ExtractionError, match="Invalid transaction amount"):
        await service.parse_document(
            file_path=Path("test.pdf"), institution="DBS", user_id=uuid4(), file_content=b"content"
        )


# ---------------------------------------------------------------------------
# extract_financial_data: PDF with file_url only, rejected (lines 393-407)
# Image with file_url only, rejected (lines 416-430)
# force_model (line 454), empty model in list (line 472),
# empty AI response (lines 493-509), return_raw (lines 512-513),
# ValueError/TypeError/KeyError/AttributeError (lines 581-590),
# fallback raise (line 604)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_pdf_with_internal_file_url_rejected():
    """PDF extraction with file_url only, internal URL rejected -> no media_payload -> error (lines 393-407)."""
    service = ExtractionService()
    service.api_key = "test-key"
    with pytest.raises(ExtractionError, match="No valid file content or accessible URL"):
        await service.extract_financial_data(
            file_content=None,
            institution="DBS",
            file_type="pdf",
            file_url="http://minio:9000/bucket/file.pdf",  # internal URL -> rejected
        )


@pytest.mark.asyncio
async def test_extract_image_with_internal_file_url_rejected():
    """Image extraction with file_url only, internal URL rejected -> error (lines 416-430)."""
    service = ExtractionService()
    service.api_key = "test-key"
    with pytest.raises(ExtractionError, match="No valid file content or accessible URL"):
        await service.extract_financial_data(
            file_content=None,
            institution="DBS",
            file_type="png",
            file_url="http://192.168.1.1:9000/bucket/file.png",  # private IP -> rejected
        )


@pytest.mark.asyncio
async def test_extract_force_model():
    """force_model parameter sets models list to [force_model] (line 454)."""
    service = ExtractionService()
    service.api_key = "test-key"

    valid_json = '{"account_last4": "1234", "transactions": []}'

    with (
        patch("src.services.extraction.stream_openrouter_json") as mock_stream,
        patch("src.services.extraction.accumulate_stream", new_callable=AsyncMock) as mock_accum,
    ):
        mock_accum.return_value = valid_json
        result = await service.extract_financial_data(
            file_content=b"content",
            institution="DBS",
            file_type="pdf",
            force_model="google/gemini-2.0-test",
        )
    assert result["account_last4"] == "1234"
    # Verify the stream was called with the force_model
    call_kwargs = mock_stream.call_args
    assert (
        call_kwargs.kwargs.get("model") == "google/gemini-2.0-test"
        or call_kwargs[1].get("model") == "google/gemini-2.0-test"
    )


@pytest.mark.asyncio
async def test_extract_empty_model_in_list_skipped():
    """Empty/falsy model in models list -> continue (line 472)."""
    service = ExtractionService()
    service.api_key = "test-key"
    service.primary_model = ""  # Empty string model

    # With empty primary_model, the only model is "", which should be skipped
    # Then we fall to line 604: raise last_error or ExtractionError(...)
    with pytest.raises(ExtractionError, match="Extraction failed after all retries"):
        await service.extract_financial_data(
            file_content=b"content",
            institution="DBS",
            file_type="pdf",
        )


@pytest.mark.asyncio
async def test_extract_empty_ai_response():
    """Empty AI response triggers error and continue (lines 493-509)."""
    service = ExtractionService()
    service.api_key = "test-key"

    with (
        patch("src.services.extraction.stream_openrouter_json"),
        patch("src.services.extraction.accumulate_stream", new_callable=AsyncMock) as mock_accum,
    ):
        mock_accum.return_value = ""  # Empty response
        with pytest.raises(ExtractionError, match="All 1 models failed.*empty_response"):
            await service.extract_financial_data(
                file_content=b"content",
                institution="DBS",
                file_type="pdf",
            )


@pytest.mark.asyncio
async def test_extract_return_raw():
    """return_raw=True returns raw AI response (lines 512-513)."""
    service = ExtractionService()
    service.api_key = "test-key"

    raw_content = '{"account_last4": "1234", "transactions": []}'

    with (
        patch("src.services.extraction.stream_openrouter_json"),
        patch("src.services.extraction.accumulate_stream", new_callable=AsyncMock) as mock_accum,
    ):
        mock_accum.return_value = raw_content
        result = await service.extract_financial_data(
            file_content=b"content",
            institution="DBS",
            file_type="pdf",
            return_raw=True,
        )
    assert "choices" in result
    assert result["choices"][0]["message"]["content"] == raw_content


@pytest.mark.asyncio
async def test_extract_value_error_during_extraction():
    """ValueError/TypeError/KeyError/AttributeError during extraction (lines 581-590)."""
    service = ExtractionService()
    service.api_key = "test-key"

    with (
        patch("src.services.extraction.stream_openrouter_json"),
        patch("src.services.extraction.accumulate_stream", new_callable=AsyncMock) as mock_accum,
    ):
        mock_accum.side_effect = ValueError("some programming error")
        with pytest.raises(ExtractionError, match="Internal error: ValueError"):
            await service.extract_financial_data(
                file_content=b"content",
                institution="DBS",
                file_type="pdf",
            )


@pytest.mark.asyncio
async def test_extract_no_models_tried_fallback_error():
    """No models tried (all empty) -> fallback raise (line 604)."""
    service = ExtractionService()
    service.api_key = "test-key"
    service.primary_model = ""

    with pytest.raises(ExtractionError, match="Extraction failed after all retries"):
        await service.extract_financial_data(
            file_content=b"content",
            institution="DBS",
            file_type="pdf",
        )


# ---------------------------------------------------------------------------
# Additional coverage tests: _safe_date None, _extract_status_code,
# _validate_balance/_compute_confidence wrappers, _build_media_payload image,
# OUT direction, OpenRouterStreamError timeout/generic, non-dict JSON,
# ExtractionError re-raise, PDF/image with valid external URL
# ---------------------------------------------------------------------------


def test_safe_date_none_or_empty():
    """_safe_date with None or empty string raises ValueError (lines 56-58)."""
    service = ExtractionService()
    with pytest.raises(ValueError, match="Date is required"):
        service._safe_date(None)
    with pytest.raises(ValueError, match="Date is required"):
        service._safe_date("")


def test_extract_status_code():
    """_extract_status_code parses HTTP status codes (lines 352-354)."""
    service = ExtractionService()
    assert service._extract_status_code("HTTP 429: Quota Exceeded") == "429"
    assert service._extract_status_code("HTTP 500 Internal Server Error") == "500"
    assert service._extract_status_code("no status code here") is None
    assert service._extract_status_code("") is None


def test_validate_balance_wrapper():
    """_validate_balance delegates to validate_balance (line 112-113)."""
    service = ExtractionService()
    result = service._validate_balance(
        {
            "opening_balance": "100.00",
            "closing_balance": "200.00",
            "transactions": [{"amount": "100.00", "direction": "IN"}],
        }
    )
    assert isinstance(result, dict)


def test_compute_confidence_wrapper():
    """_compute_confidence delegates to compute_confidence_score (line 116-117)."""
    service = ExtractionService()
    balance_result = {"balance_valid": True, "opening": "100.00", "closing": "200.00"}
    extracted = {
        "opening_balance": "100.00",
        "closing_balance": "200.00",
        "transactions": [{"amount": "100.00", "direction": "IN", "date": "2023-01-15", "description": "Test"}],
    }
    score = service._compute_confidence(extracted, balance_result)
    assert isinstance(score, int)


def test_build_media_payload_image():
    """_build_media_payload returns image_url for non-PDF (line 141)."""
    service = ExtractionService()
    result = service._build_media_payload(
        file_type="png",
        mime_type="image/png",
        data="data:image/png;base64,iVBOR",
    )
    assert result["type"] == "image_url"
    assert result["image_url"]["url"] == "data:image/png;base64,iVBOR"


@pytest.mark.asyncio
async def test_parse_document_out_direction():
    """Transaction with direction=OUT subtracts from net_transactions (line 288)."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "period_start": "2023-01-01",
            "period_end": "2023-01-31",
            "opening_balance": "500.00",
            "closing_balance": "350.00",
            "transactions": [
                {
                    "date": "2023-01-10",
                    "amount": "150.00",
                    "direction": "OUT",
                    "description": "ATM Withdrawal",
                },
            ],
        }
    )
    statement, transactions = await service.parse_document(
        file_path=Path("test.pdf"),
        institution="DBS",
        user_id=uuid4(),
        file_content=b"content",
    )
    assert len(transactions) == 1
    assert transactions[0].direction == "OUT"


@pytest.mark.asyncio
async def test_extract_non_dict_json_response():
    """AI returning a JSON array instead of object raises ExtractionError (line 517-518)."""
    service = ExtractionService()
    service.api_key = "test-key"

    with (
        patch("src.services.extraction.stream_openrouter_json"),
        patch("src.services.extraction.accumulate_stream", new_callable=AsyncMock) as mock_accum,
    ):
        mock_accum.return_value = '[{"amount": "100.00"}]'  # Array, not object
        with pytest.raises(ExtractionError, match="strict JSON object.*no arrays"):
            await service.extract_financial_data(
                file_content=b"content",
                institution="DBS",
                file_type="pdf",
            )


@pytest.mark.asyncio
async def test_extract_openrouter_timeout_error():
    """OpenRouterStreamError with timeout message (lines 556-564)."""
    from src.services.openrouter_streaming import OpenRouterStreamError

    service = ExtractionService()
    service.api_key = "test-key"

    with patch("src.services.extraction.stream_openrouter_json") as mock_stream:
        mock_stream.side_effect = OpenRouterStreamError("Request timed out after 30s")
        with pytest.raises(ExtractionError, match="timed out"):
            await service.extract_financial_data(
                file_content=b"content",
                institution="DBS",
                file_type="pdf",
            )


@pytest.mark.asyncio
async def test_extract_openrouter_generic_http_error():
    """OpenRouterStreamError with generic HTTP error (lines 565-577)."""
    from src.services.openrouter_streaming import OpenRouterStreamError

    service = ExtractionService()
    service.api_key = "test-key"

    with patch("src.services.extraction.stream_openrouter_json") as mock_stream:
        mock_stream.side_effect = OpenRouterStreamError("HTTP 502: Bad Gateway")
        with pytest.raises(ExtractionError, match="failed.*HTTP 502"):
            await service.extract_financial_data(
                file_content=b"content",
                institution="DBS",
                file_type="pdf",
            )


@pytest.mark.asyncio
async def test_extract_extraction_error_reraise():
    """ExtractionError raised during streaming is re-raised, not wrapped (line 579-580)."""
    service = ExtractionService()
    service.api_key = "test-key"

    with (
        patch("src.services.extraction.stream_openrouter_json"),
        patch("src.services.extraction.accumulate_stream", new_callable=AsyncMock) as mock_accum,
    ):
        mock_accum.side_effect = ExtractionError("Custom extraction failure")
        with pytest.raises(ExtractionError, match="Custom extraction failure"):
            await service.extract_financial_data(
                file_content=b"content",
                institution="DBS",
                file_type="pdf",
            )


@pytest.mark.asyncio
async def test_extract_pdf_with_valid_external_url():
    """PDF extraction with valid external file_url (lines 393-398)."""
    service = ExtractionService()
    service.api_key = "test-key"

    valid_json = '{"account_last4": "9999", "transactions": []}'

    with (
        patch("src.services.extraction.stream_openrouter_json"),
        patch("src.services.extraction.accumulate_stream", new_callable=AsyncMock) as mock_accum,
    ):
        mock_accum.return_value = valid_json
        result = await service.extract_financial_data(
            file_content=None,
            institution="DBS",
            file_type="pdf",
            file_url="https://example.com/statement.pdf",
        )
    assert result["account_last4"] == "9999"


@pytest.mark.asyncio
async def test_extract_image_with_valid_external_url():
    """Image extraction with valid external file_url (lines 416-422)."""
    service = ExtractionService()
    service.api_key = "test-key"

    valid_json = '{"account_last4": "8888", "transactions": []}'

    with (
        patch("src.services.extraction.stream_openrouter_json"),
        patch("src.services.extraction.accumulate_stream", new_callable=AsyncMock) as mock_accum,
    ):
        mock_accum.return_value = valid_json
        result = await service.extract_financial_data(
            file_content=None,
            institution="DBS",
            file_type="png",
            file_url="https://example.com/statement.png",
        )
    assert result["account_last4"] == "8888"


@pytest.mark.asyncio
async def test_parse_document_csv_no_institution():
    """CSV parsing without institution raises ExtractionError (line 221-222)."""
    service = ExtractionService()
    with pytest.raises(ExtractionError, match="Institution is required for CSV parsing"):
        await service.parse_document(
            file_path=Path("test.csv"),
            institution=None,
            user_id=uuid4(),
            file_type="csv",
            file_content=b"some,csv,data",
        )


@pytest.mark.asyncio
async def test_dual_write_layer2_integrity_error_is_non_fatal():
    """AC13.11.1: Dual-write handles duplicate document hash / IntegrityError without failing."""
    db = AsyncMock()
    with patch("src.services.deduplication.DeduplicationService") as mock_dedup_cls:
        mock_dedup = mock_dedup_cls.return_value
        mock_dedup.create_uploaded_document.side_effect = IntegrityError("x", {}, Exception("dup"))

        txn = MagicMock()
        txn.direction = "IN"
        txn.txn_date = date(2025, 1, 1)
        txn.amount = Decimal("1.00")
        txn.description = "txn"
        txn.reference = None
        txn.statement.currency = "SGD"
        await dual_write_layer2(
            db=db,
            user_id=uuid4(),
            file_path=Path("statement.pdf"),
            file_hash="abc123",
            original_filename="statement.pdf",
            institution="DBS",
            transactions=[txn],
        )


# ---------------------------------------------------------------------------
# Additional coverage – AC8.12.x (extraction private URL paths)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_financial_data_pdf_private_url_raises():
    """AC8.12.4 – PDF with private URL logs warning and raises ExtractionError (lines 393->403, 416->426)."""
    service = ExtractionService()
    service.api_key = "test-key"

    with pytest.raises(ExtractionError, match="No valid file content or accessible URL"):
        await service.extract_financial_data(
            file_content=None,
            institution="DBS",
            file_type="pdf",
            file_url="http://localhost:9000/private-bucket/file.pdf",
        )


@pytest.mark.asyncio
async def test_extract_financial_data_image_private_url_raises():
    """AC8.12.5 – Image with private URL logs warning and raises ExtractionError (else branch 416->426)."""
    service = ExtractionService()
    service.api_key = "test-key"

    with pytest.raises(ExtractionError, match="No valid file content or accessible URL"):
        await service.extract_financial_data(
            file_content=None,
            institution="DBS",
            file_type="png",
            file_url="http://192.168.1.100/internal/image.png",
        )