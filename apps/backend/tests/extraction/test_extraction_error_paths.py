from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text

from src.config import settings
from src.extraction import BankStatementStatus, DocumentSource
from src.extraction.base.normalization_engine import sanitize_account_last4
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.extraction.extension.statement_parsing import handle_parse_failure
from src.extraction.orm.statement_summary import StatementSummary
from src.llm import AIStreamError
from tests.extraction._statement_run_helpers import (
    assert_stream_extract_case,
    mock_statement_payload,
    mock_txn_dict,
    parse_mock_payload,
    verify_dual_write_non_fatal,
    verify_handle_parse_failure_lineage,
    verify_parse_background_storage_error,
)
from tests.factories import StatementSummaryFactory

_ABSENT = object()


async def test_handle_parse_failure_lineage_background_storage_and_dual_write(db, test_user, monkeypatch):
    await verify_handle_parse_failure_lineage(db, test_user)
    await verify_parse_background_storage_error(db, test_user, monkeypatch)
    await verify_dual_write_non_fatal(db, test_user)


@pytest.mark.parametrize(
    ("message", "expected_error", "cause_db_error"),
    [("Something went wrong", "Something went wrong", False), ("x" * 1000, "x" * 497 + "...", False), (None, None, False), ("DB error occurred", "DB error occurred", True)],
)
async def test_handle_parse_failure_variants(db, test_user, message, expected_error, cause_db_error):
    sid = uuid4()
    statement = StatementSummaryFactory.build(id=sid, user_id=test_user.id, status=BankStatementStatus.PARSING, file_hash=f"h_{sid.hex[:8]}", institution="DBS")
    db.add(statement)
    await db.commit()
    if cause_db_error:
        with pytest.raises(Exception, match="nonexistent_table_xyz"):
            await db.execute(text("SELECT * FROM nonexistent_table_xyz"))
    await handle_parse_failure(statement, db, message=message)
    result = await db.get(StatementSummary, sid)
    assert (result.status, result.validation_error, result.confidence_score) == (BankStatementStatus.REJECTED, expected_error, 0) and ((not cause_db_error) or (result.balance_validated is False))


@pytest.mark.parametrize(
    ("source", "institution", "file_type", "match"),
    [
        (DocumentSource(path=Path("test.csv"), content=None, url=None, content_hash="0" * 64, filename="test.csv"), "DBS", "csv", "File content is required for CSV parsing"),
        (DocumentSource.resolve(path=Path("test.csv"), content=b"some,csv,data"), None, "csv", "Institution is required for CSV parsing"),
        (DocumentSource.resolve(path=Path("test.exe"), content=b"content"), "DBS", "exe", "Unsupported file type: exe"),
    ],
)
async def test_parse_document_input_errors(source, institution, file_type, match):
    with pytest.raises(ExtractionError, match=match):
        await ExtractionService().parse_document(source, institution=institution, user_id=uuid4(), file_type=file_type)


@pytest.mark.parametrize(
    ("content", "file_type", "file_url", "api_key", "match"),
    [
        (None, "pdf", None, "test-key", "File content is required"),
        (b"content", "pdf", None, "", "AI provider API key not configured"),
        (None, "pdf", "http://localhost:9000/private-bucket/file.pdf", "test-key", "No valid file content or accessible URL"),
        (None, "pdf", "http://minio:9000/bucket/file.pdf", "test-key", "No valid file content or accessible URL"),
        (None, "png", "http://192.168.1.100/internal/image.png", "test-key", "No valid file content or accessible URL"),
        (None, "png", "http://192.168.1.1:9000/bucket/file.png", "test-key", "No valid file content or accessible URL"),
    ],
)
async def test_extract_financial_data_input_guards(monkeypatch, content, file_type, file_url, api_key, match):
    monkeypatch.setattr(settings, "ai_api_key", api_key)
    with pytest.raises(ExtractionError, match=match):
        await ExtractionService().extract_financial_data(content, "DBS", file_type, file_url=file_url)


@pytest.mark.parametrize(
    ("stream_exc", "accum_val", "file_content", "file_type", "file_url", "force_model", "expected", "err_match"),
    [
        (AIStreamError("HTTP 429: Quota Exceeded"), None, b"content", "pdf", "https://example.com/file.pdf", None, None, "Extraction failed \\(rate_limit\\): Model .* rate limited"),
        (AIStreamError("Request timed out after 30s"), None, b"content", "pdf", "https://example.com/file.pdf", None, None, "timed out"),
        (AIStreamError("HTTP 502: Bad Gateway"), None, b"content", "pdf", "https://example.com/file.pdf", None, None, "failed.*HTTP 502"),
        (None, 'Here is data: ```json\n{"account_last4": "1234"}\n```', b"content", "pdf", "https://example.com/file.pdf", None, {"account_last4": "1234"}, None),
        (None, "Invalid JSON without markdown that is clearly not empty", b"content", "pdf", "https://example.com/file.pdf", None, None, "strict JSON object"),
        (None, '{"account_last4": "1234", "transactions": []}', b"content", "pdf", "https://example.com/file.pdf", "google/gemini-2.0-test", {"account_last4": "1234", "transactions": []}, None),
        (None, "", b"content", "pdf", "https://example.com/file.pdf", None, None, "Extraction failed \\(empty_response\\): Model .* returned empty response"),
        (None, ValueError("some programming error"), b"content", "pdf", "https://example.com/file.pdf", None, None, "Internal error: ValueError"),
        (None, '[{"amount": "100.00"}]', b"content", "pdf", "https://example.com/file.pdf", None, None, "strict JSON object.*no arrays"),
        (None, ExtractionError("Custom extraction failure"), b"content", "pdf", "https://example.com/file.pdf", None, None, "Custom extraction failure"),
        (None, '{"account_last4": "9999", "transactions": []}', None, "pdf", "https://example.com/statement.pdf", None, {"account_last4": "9999", "transactions": []}, None),
        (None, '{"account_last4": "8888", "transactions": []}', None, "png", "https://example.com/statement.png", None, {"account_last4": "8888", "transactions": []}, None),
    ],
)
async def test_extract_financial_data_stream_outcomes(stream_exc, accum_val, file_content, file_type, file_url, force_model, expected, err_match):
    await assert_stream_extract_case(stream_exc, accum_val, file_content, file_type, file_url, force_model, expected, err_match)


async def test_extract_json_timeout_and_ai_csv_empty():
    service = ExtractionService()
    service.api_key = "test-key"
    with patch("src.extraction.extension.service.stream_ai_json", side_effect=httpx.TimeoutException("slow")), pytest.raises(ExtractionError, match="Extraction failed \\(timeout\\): Model test-vision-model timed out"):
        await service._extract_json_with_model(messages=[{"role": "user", "content": "Extract"}], model="test-vision-model")
    with patch("src.extraction.extension._csv.stream_ai_json"), patch("src.extraction.extension._csv.accumulate_stream", new_callable=AsyncMock, return_value="  "), pytest.raises(ExtractionError, match="AI CSV mapping returned empty response"):
        await service._ai_parse_csv(headers=["Date", "Description", "Amount"], rows=[{"Date": "2026-01-01", "Description": "Test", "Amount": "1.00"}], institution="DBS", parse_date=date.fromisoformat, parse_amount=Decimal)


@pytest.mark.parametrize(
    ("side_effect", "payload", "match"),
    [
        (None, mock_statement_payload({"amount": "50.00", "direction": "IN", "description": "No date"}), "Transaction missing required fields"),
        (None, mock_statement_payload({"date": "invalid-date", "amount": "50.00", "direction": "IN", "description": "Bad"}), "Transaction date"),
        (None, mock_statement_payload({"date": True, "amount": "100.00", "direction": "IN", "description": "Bool"}), "Transaction date"),
        (None, mock_statement_payload({"date": "None", "amount": "50.00", "direction": "IN", "description": "N"}, {"date": "null", "amount": "70.00", "direction": "IN", "description": "Null"}), "Transaction date"),
        (None, mock_statement_payload({"date": "2023-01-15", "amount": "not-a-number", "direction": "IN", "description": "Bad"}, closing="200.00"), "Invalid transaction amount"),
        (RuntimeError("Boom"), None, "Failed to parse document: Boom"),
    ],
)
async def test_parse_document_transaction_error_paths(side_effect, payload, match):
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(side_effect=side_effect, return_value=payload)
    with pytest.raises(ExtractionError, match=match):
        await service.parse_document(DocumentSource.resolve(path=Path("test.pdf"), content=b"content"), institution="DBS", user_id=uuid4())


@pytest.mark.parametrize(
    ("txns", "expected_descriptions", "expected_direction"),
    [
        ([mock_txn_dict(None)], ["Unknown"], "IN"),
        ([mock_txn_dict("")], ["Unknown"], "IN"),
        ([mock_txn_dict("   ")], ["Unknown"], "IN"),
        ([mock_txn_dict(_ABSENT, absent_marker=_ABSENT)], ["Unknown"], "IN"),
        ([mock_txn_dict("  Salary March  ")], ["Salary March"], "IN"),
        ([mock_txn_dict(12345)], ["12345"], "IN"),
        ([mock_txn_dict(None), mock_txn_dict(None)], ["Unknown", "Unknown"], "IN"),
        ([mock_txn_dict("ATM Withdrawal", "150.00", "OUT")], ["ATM Withdrawal"], "OUT"),
    ],
)
async def test_parse_document_normalizes_descriptions_and_direction(txns, expected_descriptions, expected_direction):
    result = await parse_mock_payload(mock_statement_payload(*txns, direction=expected_direction))
    assert ([row.description for row in result.transactions], result.transactions[0].direction, len({row.fact_id for row in result.transactions})) == (expected_descriptions, expected_direction, len(txns))


async def test_vision_paths_and_role_guards():
    service = ExtractionService()
    service.api_key, service.multimodal_model = "test-key", "test-vision-model"
    mock_extract = AsyncMock(return_value={"transactions": []})
    service._extract_json_with_model = mock_extract
    image_payload = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
    with patch.object(service, "_build_vision_media_payload_batches", return_value=[[image_payload]]):
        assert await service.extract_financial_data(b"content", "DBS", "pdf") == {"transactions": []}
    assert (mock_extract.await_args.kwargs["model"], mock_extract.await_args.kwargs["messages"][0]["content"][1]) == ("test-vision-model", image_payload)

    service.multimodal_model = ""
    with patch.object(service, "_build_vision_media_payload_batches") as bm, patch("src.extraction.extension.service.stream_ai_json") as sm, pytest.raises(ExtractionError, match="Multimodal model is not configured"):
        await service.extract_financial_data(file_content=b"content", institution="DBS", file_type="pdf")
    bm.assert_not_called()
    sm.assert_not_called()

    service = ExtractionService()
    service.api_key, service.multimodal_model = "test-key", "test-vision-model"
    attempted: list[str] = []

    def fake_stream(*, model, **_kwargs):
        attempted.append(model)
        raise AIStreamError('provider=zai model=test-vision-model status_code=400 {"code":"1210","message":"Invalid API parameter"}', retryable=False)

    with patch.object(service, "_build_vision_media_payload_batches", return_value=[[image_payload]]), patch("src.extraction.extension.service.stream_ai_json", side_effect=fake_stream), pytest.raises(ExtractionError, match="Extraction failed \\(http_error\\): Model test-vision-model failed"):
        await service.extract_financial_data(b"content", "DBS", "pdf")
    assert attempted == ["test-vision-model"] and service.multimodal_model == "test-vision-model"
    assert all(not hasattr(service, r) for r in ("ocr_model", "vision_model", "_vision_extraction_models", "_uses_dedicated_layout_ocr", "_extract_ocr_markdown", "_extract_json_with_models"))
    with pytest.raises(ExtractionError, match="requires file content"):
        service._render_pdf_pages_as_image_payload_batches(b"")


@pytest.mark.parametrize(
    ("provider", "patch_target", "side_effect", "file_content", "file_url", "err_match"),
    [
        ("zai", "_build_ai_file_input", "data:application/pdf;base64,abc", None, "https://example.com/statement.pdf", "requires file content or an external PDF URL"),
        ("zai", "_render_pdf_pages_as_image_payload_batches", ExtractionError("render failed"), b"pdf bytes", None, "render failed"),
        ("gemini", "_render_pdf_pages_as_image_payload_batches", AssertionError("Gemini must not render PDF pages to images"), b"%PDF-1.4 fake pdf bytes", None, None),
    ],
)
def test_build_vision_media_payload_batches_variants(monkeypatch, provider, patch_target, side_effect, file_content, file_url, err_match):
    monkeypatch.setattr(settings, "ai_provider", provider)
    service = ExtractionService()
    patch_kw = {"return_value": side_effect} if isinstance(side_effect, str) else {"side_effect": side_effect}
    with patch.object(service, patch_target, **patch_kw):
        if err_match:
            with pytest.raises(ExtractionError, match=err_match):
                service._build_vision_media_payload_batches(file_content=file_content, file_url=file_url, file_type="pdf", mime_type="application/pdf")
        else:
            batches = service._build_vision_media_payload_batches(file_content=file_content, file_url=file_url, file_type="pdf", mime_type="application/pdf")
            assert len(batches) == len(batches[0]) == 1 and batches[0][0]["type"] == "file" and batches[0][0]["file"]["file_data"].startswith("data:application/pdf;base64,")


def test_extraction_service_low_level_helpers():
    service = ExtractionService()
    assert (service._safe_decimal("1.23"), service._safe_decimal(None), service._safe_decimal(None, default="42.50")) == (Decimal("1.23"), None, Decimal("42.50"))
    for fn, arg, match in [(service._safe_decimal, "not-a-number", "Invalid decimal value"), (lambda x: service._safe_decimal(x, required=True), None, "Decimal value is required"), (service._safe_date, "not-a-date", "Invalid date format"), (service._safe_date, None, "Date is required"), (service._safe_date, "", "Date is required")]:
        with pytest.raises(ValueError, match=match):
            fn(arg)
    assert all(service._validate_external_url(u) is ok for u, ok in [("http:///path", False), ("http://localhost:8000", False), ("http://192.168.1.1", False), ("http://minio:9000", False), ("https://google.com", True), ("not a url", False), (cast(str, None), False), (cast(str, object()), False)])
    assert (service._extract_status_code("HTTP 429: Quota Exceeded"), service._extract_status_code("HTTP 500 Internal Server Error"), service._extract_status_code("no status code here"), service._extract_status_code("")) == ("429", "500", None, None)
    assert service._build_media_payload(file_type="png", mime_type="image/png", data="data:image/png;base64,iVBOR") == {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBOR"}}


@pytest.mark.parametrize(("raw", "expected"), [("553-3", "5533"), ("XXX-553-3", "5533"), (None, None), ("", None), ("12", "12"), ("---", None), ("1234", "1234"), ("12 34", "1234"), ("AB-12", "AB12"), ("ABCDEF1234", "1234"), ("12号34", "1234"), ("A", "A")])
def test_sanitize_account_last4(raw, expected):
    assert sanitize_account_last4(raw) == expected
