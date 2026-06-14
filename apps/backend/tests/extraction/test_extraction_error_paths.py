from datetime import date
from decimal import Decimal  # noqa: F401
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.models.layer1 import DocumentStatus, UploadedDocument
from src.models.statement_enums import BankStatementStatus
from src.models.statement_summary import StatementSummary
from src.services.deduplication import dual_write_layer2
from src.services.extraction import ExtractionError, ExtractionService
from src.services.statement_parsing import handle_parse_failure
from tests.factories import StatementSummaryFactory


async def mock_stream_generator(content: str):
    """Helper to create async generator for streaming mock."""
    yield content


async def test_handle_parse_failure_persists_failed_document_lineage(db, test_user):
    """AC16.22.10: a hard parse failure persists an UploadedDocument(failed) so the uploaded raw
    file stays traceable from the rejected statement (#982). The document is normally created on
    success in dual_write; a failure happens before that, so without this the raw file is orphaned.
    """
    statement = await StatementSummaryFactory.create_async(db, user_id=test_user.id, status=BankStatementStatus.PARSING)
    await db.commit()

    await handle_parse_failure(
        statement,
        db,
        message="All 1 models failed. Breakdown: 1 json_parse.",
        file_hash=statement.file_hash,
        storage_key=f"statements/{statement.id}/abc123.pdf",
        original_filename="futu-2506.pdf",
    )

    doc = (
        await db.execute(
            select(UploadedDocument)
            .where(UploadedDocument.user_id == test_user.id)
            .where(UploadedDocument.file_hash == statement.file_hash)
        )
    ).scalar_one()
    assert doc.status == DocumentStatus.FAILED
    assert doc.original_filename == "futu-2506.pdf"
    # The raw file must stay retrievable: the document points at the storage key we uploaded to.
    assert doc.file_path == f"statements/{statement.id}/abc123.pdf"

    refreshed = await db.get(StatementSummary, statement.id)
    assert refreshed.status == BankStatementStatus.REJECTED
    assert refreshed.uploaded_document_id == doc.id


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


async def test_extract_financial_data_no_content_no_url():
    service = ExtractionService()
    with pytest.raises(ExtractionError, match="File content is required"):
        await service.extract_financial_data(None, "DBS", "pdf")


async def test_extract_financial_data_no_api_key(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "ai_api_key", "")
    service = ExtractionService()
    with pytest.raises(ExtractionError, match="AI provider API key not configured"):
        await service.extract_financial_data(b"content", "DBS", "pdf")


async def test_extract_ocr_markdown_joins_layout_results(monkeypatch):
    service = ExtractionService()
    service.api_key = "test-key"

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"md_results": ["# Statement", "", "Balance: 10.00"]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers, json):
            assert url.endswith("/layout_parsing")
            assert headers["Authorization"] == "Bearer test-key"
            assert json["model"] == service.ocr_model
            assert json["file"].startswith("data:application/pdf;base64,")
            return FakeResponse()

    monkeypatch.setattr("src.services.extraction.httpx.AsyncClient", FakeClient)

    markdown = await service._extract_ocr_markdown(
        file_content=b"pdf bytes",
        file_url=None,
        file_type="pdf",
        mime_type="application/pdf",
    )

    assert markdown == "# Statement\n\nBalance: 10.00"


def test_validate_external_url_handles_unexpected_input():
    service = ExtractionService()

    assert service._validate_external_url(cast(str, object())) is False


async def test_extract_ocr_markdown_rejects_empty_layout_result(monkeypatch):
    service = ExtractionService()
    service.api_key = "test-key"

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"md_results": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers, json):
            return FakeResponse()

    monkeypatch.setattr("src.services.extraction.httpx.AsyncClient", FakeClient)

    with pytest.raises(ExtractionError, match="empty Markdown"):
        await service._extract_ocr_markdown(
            file_content=b"pdf bytes",
            file_url=None,
            file_type="pdf",
            mime_type="application/pdf",
        )


async def test_extract_json_with_models_skips_empty_model_entries():
    service = ExtractionService()

    with pytest.raises(ExtractionError, match="Extraction failed after all retries"):
        await service._extract_json_with_models(
            messages=[{"role": "user", "content": "Extract"}],
            models=[""],
            prompt="Extract",
            institution="DBS",
            file_type="pdf",
            return_raw=False,
            has_content=True,
            has_url=False,
        )


async def test_extract_financial_data_uses_ocr_first_pipeline():
    service = ExtractionService()
    service.api_key = "test-key"
    service.ocr_model = "dedicated-layout-model"
    service.vision_model = "glm-4.6v"

    mock_ocr = AsyncMock(return_value="| Date | Amount |\n| 2025-01-01 | 10.00 |")
    mock_extract = AsyncMock(return_value={"transactions": []})
    service._extract_ocr_markdown = mock_ocr
    service._extract_json_with_models = mock_extract

    result = await service.extract_financial_data(b"content", "DBS", "pdf")

    assert result == {"transactions": []}
    mock_ocr.assert_awaited_once_with(b"content", None, "pdf", "application/pdf")
    call = mock_extract.await_args.kwargs
    assert call["models"] == [service.primary_model, *service.fallback_models]
    assert "OCR Markdown" in call["messages"][0]["content"]


async def test_extract_financial_data_shared_ocr_vision_skips_layout_parser():
    """AC8.12.6: Shared OCR/vision model uses one vision call and skips layout parsing.

    AC13.17.1: the configured vision fallback model is appended after the primary
    so more than one model is attempted on the vision path (#1034).
    """
    service = ExtractionService()
    service.api_key = "test-key"
    service.ocr_model = "glm-4.6v"
    service.vision_model = "glm-4.6v"
    service.vision_fallback_models = ["glm-4.5v"]

    mock_ocr = AsyncMock()
    mock_extract = AsyncMock(return_value={"transactions": []})
    service._extract_ocr_markdown = mock_ocr
    service._extract_json_with_models = mock_extract
    image_payload = {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
    }

    with patch.object(service, "_build_vision_media_payloads", return_value=[image_payload]):
        result = await service.extract_financial_data(b"content", "DBS", "pdf")

    assert result == {"transactions": []}
    mock_ocr.assert_not_awaited()
    call = mock_extract.await_args.kwargs
    assert call["models"] == ["glm-4.6v", "glm-4.5v"]
    assert call["messages"][0]["content"][1] == image_payload


async def test_vision_path_falls_back_to_secondary_model_on_non_retryable_error():
    """AC13.17.2: when the primary vision model raises a non-retryable provider
    error (e.g. a 400), the vision path attempts the configured vision fallback
    model and succeeds instead of failing the upload (#1034)."""
    from src.services.ai_streaming import AIStreamError

    service = ExtractionService()
    service.api_key = "test-key"
    service.ocr_model = "glm-4.6v"
    service.vision_model = "glm-4.6v"
    service.vision_fallback_models = ["glm-4.5v"]

    attempted_models: list[str] = []

    def fake_stream_ai_json(*, model, **kwargs):
        attempted_models.append(model)
        if model == "glm-4.6v":
            raise AIStreamError(
                'provider=zai model=glm-4.6v status_code=400 {"code":"1210","message":"Invalid API parameter"}',
                retryable=False,
            )
        return f"stream:{model}"

    async def fake_accumulate_stream(stream):
        assert stream == "stream:glm-4.5v"
        return '{"transactions": []}'

    image_payload = {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
    }

    with (
        patch.object(service, "_build_vision_media_payloads", return_value=[image_payload]),
        patch("src.services.extraction.stream_ai_json", side_effect=fake_stream_ai_json),
        patch("src.services.extraction.accumulate_stream", side_effect=fake_accumulate_stream),
    ):
        result = await service.extract_financial_data(b"content", "DBS", "pdf")

    assert result == {"transactions": []}
    # The primary vision model is attempted first, then the configured fallback.
    assert attempted_models == ["glm-4.6v", "glm-4.5v"]


def test_ocr_model_selection_helpers_deduplicate_vision_models():
    """AC8.12.6: OCR/vision helper rules avoid duplicate provider calls.

    AC13.17.1: configured vision fallbacks are appended to the vision model list,
    deduplicated and order-preserving, so more than one model is attempted on the
    vision path (#1034).
    """
    service = ExtractionService()
    service.vision_fallback_models = ["glm-4.5v"]

    service.ocr_model = "glm-4.6v"
    service.vision_model = "glm-4.6v"
    assert service._uses_dedicated_layout_ocr() is False
    assert service._vision_extraction_models() == ["glm-4.6v", "glm-4.5v"]

    service.ocr_model = "layout-ocr-model"
    service.vision_model = "glm-4.6v"
    assert service._uses_dedicated_layout_ocr() is True
    assert service._vision_extraction_models() == ["layout-ocr-model", "glm-4.6v", "glm-4.5v"]

    service.ocr_model = ""
    service.vision_model = "glm-4.6v"
    assert service._uses_dedicated_layout_ocr() is False
    assert service._vision_extraction_models() == ["glm-4.6v", "glm-4.5v"]


def test_vision_extraction_models_dedupes_fallback_against_primary():
    """AC13.17.1: a vision fallback equal to the primary vision/OCR model is not
    attempted twice; ordering of the remaining fallbacks is preserved (#1034)."""
    service = ExtractionService()
    service.ocr_model = "glm-4.6v"
    service.vision_model = "glm-4.6v"
    service.vision_fallback_models = ["glm-4.6v", "glm-4.5v", "glm-4.5v"]

    assert service._vision_extraction_models() == ["glm-4.6v", "glm-4.5v"]


def test_vision_extraction_models_without_fallbacks_returns_primary_only():
    """AC13.17.1: with no configured vision fallbacks the list is unchanged, so
    deployments that opt out keep the prior single-model behavior (#1034)."""
    service = ExtractionService()
    service.ocr_model = "glm-4.6v"
    service.vision_model = "glm-4.6v"
    service.vision_fallback_models = []

    assert service._vision_extraction_models() == ["glm-4.6v"]


def test_render_pdf_pages_rejects_empty_content():
    """AC8.12.6: PDF vision rendering fails fast when no bytes are available."""
    service = ExtractionService()

    with pytest.raises(ExtractionError, match="requires file content"):
        service._render_pdf_pages_as_image_payloads(b"")


def test_build_vision_media_payloads_rejects_non_url_pdf_input(monkeypatch):
    """AC8.12.6: Z.AI PDF vision payloads require rendered content or an external URL."""
    from src.config import settings

    monkeypatch.setattr(settings, "ai_provider", "zai")
    service = ExtractionService()

    with patch.object(service, "_build_ai_file_input", return_value="data:application/pdf;base64,abc"):
        with pytest.raises(ExtractionError, match="requires file content or an external PDF URL"):
            service._build_vision_media_payloads(
                file_content=None,
                file_url="https://example.com/statement.pdf",
                file_type="pdf",
                mime_type="application/pdf",
            )


def test_build_vision_media_payloads_reraises_render_error_without_external_url(monkeypatch):
    """AC8.12.6: Render failures without a safe external URL do not silently continue."""
    from src.config import settings

    monkeypatch.setattr(settings, "ai_provider", "zai")
    service = ExtractionService()

    with patch.object(
        service,
        "_render_pdf_pages_as_image_payloads",
        side_effect=ExtractionError("render failed"),
    ):
        with pytest.raises(ExtractionError, match="render failed"):
            service._build_vision_media_payloads(
                file_content=b"pdf bytes",
                file_url=None,
                file_type="pdf",
                mime_type="application/pdf",
            )


async def test_extract_ocr_markdown_surfaces_layout_http_error(monkeypatch):
    """AC8.12.6: Dedicated OCR layout HTTP failures include status and body."""
    service = ExtractionService()
    service.api_key = "test-key"

    class FakeResponse:
        status_code = 503
        text = "provider unavailable"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers, json):
            return FakeResponse()

    monkeypatch.setattr("src.services.extraction.httpx.AsyncClient", FakeClient)

    with pytest.raises(ExtractionError, match="HTTP 503: provider unavailable"):
        await service._extract_ocr_markdown(
            file_content=b"pdf bytes",
            file_url=None,
            file_type="pdf",
            mime_type="application/pdf",
        )


async def test_extract_json_with_models_handles_httpx_timeout():
    """AC8.12.6: Native httpx timeouts are summarized like provider timeouts."""
    import httpx

    service = ExtractionService()

    with patch("src.services.extraction.stream_ai_json", side_effect=httpx.TimeoutException("slow")):
        with pytest.raises(ExtractionError, match="All 1 models failed.*timeout"):
            await service._extract_json_with_models(
                messages=[{"role": "user", "content": "Extract"}],
                models=["glm-4.6v"],
                prompt="Extract",
                institution="DBS",
                file_type="pdf",
                return_raw=False,
                has_content=True,
                has_url=False,
            )


async def test_ai_parse_csv_empty_mapping_response():
    """AC8.12.6: AI CSV mapping rejects empty model responses."""
    service = ExtractionService()
    service.api_key = "test-key"

    with (
        patch("src.services.ai_streaming.stream_ai_json"),
        patch("src.services.ai_streaming.accumulate_stream", new_callable=AsyncMock) as mock_accum,
    ):
        mock_accum.return_value = "  "
        with pytest.raises(ExtractionError, match="AI CSV mapping returned empty response"):
            await service._ai_parse_csv(
                headers=["Date", "Description", "Amount"],
                rows=[{"Date": "2026-01-01", "Description": "Test", "Amount": "1.00"}],
                institution="DBS",
                parse_date=lambda value: date.fromisoformat(value),
                parse_amount=lambda value: Decimal(value),
            )


async def test_extract_financial_data_dedicated_ocr_failure_falls_back_to_vision():
    """AC8.12.6: Dedicated OCR failure falls back to ordered vision extraction models."""
    service = ExtractionService()
    service.api_key = "test-key"
    service.ocr_model = "layout-ocr-model"
    service.vision_model = "glm-4.6v"
    service.vision_fallback_models = ["glm-4.5v"]

    mock_ocr = AsyncMock(side_effect=ExtractionError("layout parser unavailable"))
    mock_extract = AsyncMock(return_value={"transactions": []})
    service._extract_ocr_markdown = mock_ocr
    service._extract_json_with_models = mock_extract
    image_payload = {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
    }

    with patch.object(service, "_build_vision_media_payloads", return_value=[image_payload]):
        result = await service.extract_financial_data(b"content", "DBS", "pdf")

    assert result == {"transactions": []}
    mock_ocr.assert_awaited_once_with(b"content", None, "pdf", "application/pdf")
    call = mock_extract.await_args.kwargs
    # AC13.17.1: the vision fallback model is appended after the primary vision model.
    assert call["models"] == ["layout-ocr-model", "glm-4.6v", "glm-4.5v"]
    assert call["messages"][0]["content"][1] == image_payload


async def test_extract_financial_data_all_models_fail():
    service = ExtractionService()
    service.api_key = "test-key"
    service.ocr_model = None

    from src.services.ai_streaming import AIStreamError

    with patch("src.services.extraction.stream_ai_json") as mock_stream:
        mock_stream.side_effect = AIStreamError("HTTP 429: Quota Exceeded")

        with pytest.raises(ExtractionError, match="rate limited"):
            await service.extract_financial_data(
                b"content",
                "DBS",
                "pdf",
                file_url="https://example.com/file.pdf",
            )


async def test_extract_financial_data_json_markdown_fallback():
    """AC13.14.5: a markdown-fenced but otherwise-valid response is salvaged (#982)."""
    service = ExtractionService()
    service.api_key = "test-key"
    service.ocr_model = None

    content = 'Here is data: ```json\n{"account_last4": "1234"}\n```'

    with patch("src.services.extraction.stream_ai_json") as mock_stream:
        mock_stream.return_value = mock_stream_generator(content)

        result = await service.extract_financial_data(
            b"content",
            "DBS",
            "pdf",
            file_url="https://example.com/file.pdf",
        )
        assert result == {"account_last4": "1234"}


async def test_extract_financial_data_invalid_json_all_attempts():
    service = ExtractionService()
    service.api_key = "test-key"
    service.ocr_model = None
    service.vision_fallback_models = []  # isolate single-model JSON-parse behavior

    # Invalid JSON - should fail with JSON parse error immediately
    content = "Invalid JSON without markdown that is clearly not empty"

    with patch("src.services.extraction.stream_ai_json") as mock_stream:
        mock_stream.return_value = mock_stream_generator(content)

        # Now expects JSON parse error, not "all models failed"
        with pytest.raises(ExtractionError, match="strict JSON object"):
            await service.extract_financial_data(
                b"content",
                "DBS",
                "pdf",
                file_url="https://example.com/file.pdf",
            )


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


async def test_handle_parse_failure(db, test_user):
    from src.services.statement_parsing import handle_parse_failure

    sid = uuid4()
    statement = StatementSummaryFactory.build(
        id=sid,
        user_id=test_user.id,
        status=BankStatementStatus.PARSING,
        file_hash="h_fail",
        institution="DBS",
    )
    db.add(statement)
    await db.commit()

    await handle_parse_failure(statement, db, message="Something went wrong")

    await db.refresh(statement)
    assert statement.status == BankStatementStatus.REJECTED
    assert statement.validation_error == "Something went wrong"
    assert statement.confidence_score == 0


async def test_parse_statement_background_storage_error(db, test_user, monkeypatch):
    from src.database import create_session_maker_from_db
    from src.services.statement_parsing import parse_statement_background
    from src.services.storage import StorageError

    sid = uuid4()
    uid = test_user.id
    statement = StatementSummaryFactory.build(
        id=sid,
        user_id=uid,
        status=BankStatementStatus.PARSING,
        file_hash="h_storage_err",
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


async def test_handle_parse_failure_truncates_long_message(db, test_user):
    from src.services.statement_parsing import handle_parse_failure

    sid = uuid4()
    statement = StatementSummaryFactory.build(
        id=sid,
        user_id=test_user.id,
        status=BankStatementStatus.PARSING,
        file_hash="h_trunc",
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


async def test_handle_parse_failure_after_db_error(db, test_user):
    """Handler recovers from a session with pending rollback error."""
    from sqlalchemy import text

    from src.services.statement_parsing import handle_parse_failure

    sid = uuid4()
    statement = StatementSummaryFactory.build(
        id=sid,
        user_id=test_user.id,
        status=BankStatementStatus.PARSING,
        file_hash="h_dberr",
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
    from src.models.statement_summary import StatementSummary

    result = await db.get(StatementSummary, sid)
    assert result is not None
    assert result.status == BankStatementStatus.REJECTED
    assert result.validation_error == "DB error occurred"
    assert result.confidence_score == 0
    assert result.balance_validated is False


async def test_handle_parse_failure_none_message(db, test_user):
    from src.services.statement_parsing import handle_parse_failure

    sid = uuid4()
    statement = StatementSummaryFactory.build(
        id=sid,
        user_id=test_user.id,
        status=BankStatementStatus.PARSING,
        file_hash="h_none_msg",
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


async def test_extract_force_model():
    """force_model parameter sets models list to [force_model] (line 454)."""
    service = ExtractionService()
    service.api_key = "test-key"

    valid_json = '{"account_last4": "1234", "transactions": []}'

    with (
        patch("src.services.extraction.stream_ai_json") as mock_stream,
        patch("src.services.extraction.accumulate_stream", new_callable=AsyncMock) as mock_accum,
    ):
        mock_accum.return_value = valid_json
        result = await service.extract_financial_data(
            file_content=b"content",
            file_url="https://example.com/file.pdf",
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


async def test_extract_empty_model_in_list_skipped():
    """Empty/falsy model in models list -> continue (line 472)."""
    service = ExtractionService()
    service.api_key = "test-key"
    service.primary_model = ""  # Empty string model
    service.ocr_model = ""
    service.vision_model = ""
    service.vision_fallback_models = []  # no fallbacks -> empty model list

    # With empty primary_model, the only model is "", which should be skipped
    # Then we fall to line 604: raise last_error or ExtractionError(...)
    with pytest.raises(ExtractionError, match="Extraction failed after all retries"):
        await service.extract_financial_data(
            file_content=b"content",
            institution="DBS",
            file_type="pdf",
        )


async def test_extract_empty_ai_response():
    """Empty AI response triggers error and continue (lines 493-509)."""
    service = ExtractionService()
    service.api_key = "test-key"
    service.ocr_model = None
    service.vision_fallback_models = []  # isolate single-model empty-response behavior

    with (
        patch("src.services.extraction.stream_ai_json"),
        patch("src.services.extraction.accumulate_stream", new_callable=AsyncMock) as mock_accum,
    ):
        mock_accum.return_value = ""  # Empty response
        with pytest.raises(ExtractionError, match="All 1 models failed.*empty_response"):
            await service.extract_financial_data(
                file_content=b"content",
                file_url="https://example.com/file.pdf",
                institution="DBS",
                file_type="pdf",
            )


async def test_extract_return_raw():
    """return_raw=True returns raw AI response (lines 512-513)."""
    service = ExtractionService()
    service.api_key = "test-key"
    service.ocr_model = None

    raw_content = '{"account_last4": "1234", "transactions": []}'

    with (
        patch("src.services.extraction.stream_ai_json"),
        patch("src.services.extraction.accumulate_stream", new_callable=AsyncMock) as mock_accum,
    ):
        mock_accum.return_value = raw_content
        result = await service.extract_financial_data(
            file_content=b"content",
            file_url="https://example.com/file.pdf",
            institution="DBS",
            file_type="pdf",
            return_raw=True,
        )
    assert "choices" in result
    assert result["choices"][0]["message"]["content"] == raw_content


async def test_extract_value_error_during_extraction():
    """ValueError/TypeError/KeyError/AttributeError during extraction (lines 581-590)."""
    service = ExtractionService()
    service.api_key = "test-key"
    service.ocr_model = None

    with (
        patch("src.services.extraction.stream_ai_json"),
        patch("src.services.extraction.accumulate_stream", new_callable=AsyncMock) as mock_accum,
    ):
        mock_accum.side_effect = ValueError("some programming error")
        with pytest.raises(ExtractionError, match="Internal error: ValueError"):
            await service.extract_financial_data(
                file_content=b"content",
                file_url="https://example.com/file.pdf",
                institution="DBS",
                file_type="pdf",
            )


async def test_extract_no_models_tried_fallback_error():
    """No models tried (all empty) -> fallback raise (line 604)."""
    service = ExtractionService()
    service.api_key = "test-key"
    service.primary_model = ""
    service.ocr_model = ""
    service.vision_model = ""
    service.vision_fallback_models = []  # no fallbacks -> empty model list

    with pytest.raises(ExtractionError, match="Extraction failed after all retries"):
        await service.extract_financial_data(
            file_content=b"content",
            institution="DBS",
            file_type="pdf",
        )


# ---------------------------------------------------------------------------
# Additional coverage tests: _safe_date None, _extract_status_code,
# _build_media_payload image,
# OUT direction, AIStreamError timeout/generic, non-dict JSON,
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


async def test_extract_non_dict_json_response():
    """AI returning a JSON array instead of object raises ExtractionError (line 517-518)."""
    service = ExtractionService()
    service.api_key = "test-key"
    service.ocr_model = None

    with (
        patch("src.services.extraction.stream_ai_json"),
        patch("src.services.extraction.accumulate_stream", new_callable=AsyncMock) as mock_accum,
    ):
        mock_accum.return_value = '[{"amount": "100.00"}]'  # Array, not object
        with pytest.raises(ExtractionError, match="strict JSON object.*no arrays"):
            await service.extract_financial_data(
                file_content=b"content",
                file_url="https://example.com/file.pdf",
                institution="DBS",
                file_type="pdf",
            )


async def test_extract_openrouter_timeout_error():
    """AIStreamError with timeout message (lines 556-564)."""
    from src.services.ai_streaming import AIStreamError

    service = ExtractionService()
    service.api_key = "test-key"
    service.ocr_model = None

    with patch("src.services.extraction.stream_ai_json") as mock_stream:
        mock_stream.side_effect = AIStreamError("Request timed out after 30s")
        with pytest.raises(ExtractionError, match="timed out"):
            await service.extract_financial_data(
                file_content=b"content",
                file_url="https://example.com/file.pdf",
                institution="DBS",
                file_type="pdf",
            )


async def test_extract_openrouter_generic_http_error():
    """AIStreamError with generic HTTP error (lines 565-577)."""
    from src.services.ai_streaming import AIStreamError

    service = ExtractionService()
    service.api_key = "test-key"
    service.ocr_model = None

    with patch("src.services.extraction.stream_ai_json") as mock_stream:
        mock_stream.side_effect = AIStreamError("HTTP 502: Bad Gateway")
        with pytest.raises(ExtractionError, match="failed.*HTTP 502"):
            await service.extract_financial_data(
                file_content=b"content",
                file_url="https://example.com/file.pdf",
                institution="DBS",
                file_type="pdf",
            )


async def test_extract_extraction_error_reraise():
    """ExtractionError raised during streaming is re-raised, not wrapped (line 579-580)."""
    service = ExtractionService()
    service.api_key = "test-key"
    service.ocr_model = None

    with (
        patch("src.services.extraction.stream_ai_json"),
        patch("src.services.extraction.accumulate_stream", new_callable=AsyncMock) as mock_accum,
    ):
        mock_accum.side_effect = ExtractionError("Custom extraction failure")
        with pytest.raises(ExtractionError, match="Custom extraction failure"):
            await service.extract_financial_data(
                file_content=b"content",
                file_url="https://example.com/file.pdf",
                institution="DBS",
                file_type="pdf",
            )


async def test_extract_pdf_with_valid_external_url():
    """PDF extraction with valid external file_url (lines 393-398)."""
    service = ExtractionService()
    service.api_key = "test-key"
    service.ocr_model = None

    valid_json = '{"account_last4": "9999", "transactions": []}'

    with (
        patch("src.services.extraction.stream_ai_json"),
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


async def test_extract_image_with_valid_external_url():
    """Image extraction with valid external file_url (lines 416-422)."""
    service = ExtractionService()
    service.api_key = "test-key"

    valid_json = '{"account_last4": "8888", "transactions": []}'

    with (
        patch("src.services.extraction.stream_ai_json"),
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


async def test_dual_write_layer2_integrity_error_is_non_fatal():
    """AC13.11.1: Dual-write handles duplicate document hash / IntegrityError without failing."""
    db = AsyncMock()
    # No pre-existing UploadedDocument for (user_id, file_hash), so dual_write takes the
    # create branch; a concurrent race then makes create_uploaded_document raise
    # IntegrityError, which must be swallowed without failing ingestion.
    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None
    db.execute.return_value = no_existing
    with patch("src.services.deduplication.DeduplicationService") as mock_dedup_cls:
        mock_dedup = mock_dedup_cls.return_value
        mock_dedup.create_uploaded_document.side_effect = IntegrityError("x", {}, Exception("dup"))

        txn = MagicMock()
        txn.direction = "IN"
        txn.txn_date = date(2025, 1, 1)
        txn.amount = Decimal("1.00")
        txn.description = "txn"
        txn.reference = None
        txn.currency = "SGD"
        statement = StatementSummaryFactory.build(
            user_id=uuid4(),
            file_hash="abc123",
            institution="DBS",
            currency="SGD",
        )
        await dual_write_layer2(
            db=db,
            user_id=uuid4(),
            statement=statement,
            transactions=[txn],
            file_path=Path("statement.pdf"),
            original_filename="statement.pdf",
        )


# ---------------------------------------------------------------------------
# Additional coverage – AC8.12.x (extraction private URL paths)
# ---------------------------------------------------------------------------


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
