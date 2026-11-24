from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
from pydantic_ai.exceptions import (
    ModelHTTPError,
    ModelTimeoutError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
    UserError,
)
from sqlalchemy import text

from src.config import settings
from src.extraction import BankStatementStatus, DocumentSource
from src.extraction.base.decoding import EXTRACTION_TIMEOUT_SECONDS
from src.extraction.base.normalization_engine import sanitize_account_last4
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.extraction.extension.statement_parsing import handle_parse_failure
from src.extraction.orm.statement_summary import StatementSummary
from src.llm import ModelCallFailed, ModelFailureKind
from tests._support.fake_llm import install_fake_model
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
    [
        ("Something went wrong", "Something went wrong", False),
        ("x" * 1000, "x" * 497 + "...", False),
        (None, None, False),
        ("DB error occurred", "DB error occurred", True),
    ],
)
async def test_handle_parse_failure_variants(db, test_user, message, expected_error, cause_db_error):
    sid = uuid4()
    statement = StatementSummaryFactory.build(
        id=sid,
        user_id=test_user.id,
        status=BankStatementStatus.PARSING,
        file_hash=f"h_{sid.hex[:8]}",
        institution="DBS",
    )
    db.add(statement)
    await db.commit()
    if cause_db_error:
        with pytest.raises(Exception, match="nonexistent_table_xyz"):
            await db.execute(text("SELECT * FROM nonexistent_table_xyz"))
    await handle_parse_failure(statement, db, message=message)
    result = await db.get(StatementSummary, sid)
    assert (result.status, result.validation_error, result.confidence_score) == (
        BankStatementStatus.REJECTED,
        expected_error,
        0,
    ) and ((not cause_db_error) or (result.balance_validated is False))


@pytest.mark.parametrize(
    ("source", "institution", "file_type", "match"),
    [
        (
            DocumentSource(path=Path("test.csv"), content=None, url=None, content_hash="0" * 64, filename="test.csv"),
            "DBS",
            "csv",
            "File content is required for CSV parsing",
        ),
        (
            DocumentSource.resolve(path=Path("test.csv"), content=b"some,csv,data"),
            None,
            "csv",
            "Institution is required for CSV parsing",
        ),
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
        (
            None,
            "pdf",
            "http://localhost:9000/private-bucket/file.pdf",
            "test-key",
            "No valid file content or accessible URL",
        ),
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
        (
            ModelHTTPError(status_code=429, model_name="m", body={"error": "quota"}),
            None,
            b"content",
            "pdf",
            "https://example.com/file.pdf",
            None,
            None,
            "Extraction failed \\(rate_limit\\): Model .* rate limited",
        ),
        (
            ModelTimeoutError("m", "Request timed out after 30s"),
            None,
            b"content",
            "pdf",
            "https://example.com/file.pdf",
            None,
            None,
            "timed out",
        ),
        (
            ModelHTTPError(status_code=502, model_name="m", body="Bad Gateway"),
            None,
            b"content",
            "pdf",
            "https://example.com/file.pdf",
            None,
            None,
            "Extraction failed \\(http_error\\): Model .* failed: .*502",
        ),
        (
            None,
            'Here is data: ```json\n{"account_last4": "1234"}\n```',
            b"content",
            "pdf",
            "https://example.com/file.pdf",
            None,
            {"account_last4": "1234"},
            None,
        ),
        (
            None,
            "Invalid JSON without markdown that is clearly not empty",
            b"content",
            "pdf",
            "https://example.com/file.pdf",
            None,
            None,
            "strict JSON object",
        ),
        (
            None,
            '{"account_last4": "1234", "transactions": []}',
            b"content",
            "pdf",
            "https://example.com/file.pdf",
            "google/gemini-2.0-test",
            {"account_last4": "1234", "transactions": []},
            None,
        ),
        (
            None,
            "",
            b"content",
            "pdf",
            "https://example.com/file.pdf",
            None,
            None,
            "Extraction failed \\(empty_response\\): Model .* returned empty response",
        ),
        (
            None,
            ValueError("some programming error"),
            b"content",
            "pdf",
            "https://example.com/file.pdf",
            None,
            None,
            "Extraction failed \\(model_error\\): Model .* failed: ValueError",
        ),
        (
            None,
            '[{"amount": "100.00"}]',
            b"content",
            "pdf",
            "https://example.com/file.pdf",
            None,
            None,
            "strict JSON object.*no arrays",
        ),
        (
            None,
            '{"account_last4": "9999", "transactions": []}',
            None,
            "pdf",
            "https://example.com/statement.pdf",
            None,
            {"account_last4": "9999", "transactions": []},
            None,
        ),
        (
            None,
            '{"account_last4": "8888", "transactions": []}',
            None,
            "png",
            "https://example.com/statement.png",
            None,
            {"account_last4": "8888", "transactions": []},
            None,
        ),
    ],
)
async def test_extract_financial_data_stream_outcomes(
    monkeypatch, stream_exc, accum_val, file_content, file_type, file_url, force_model, expected, err_match
):
    await assert_stream_extract_case(
        monkeypatch, stream_exc, accum_val, file_content, file_type, file_url, force_model, expected, err_match
    )


@pytest.mark.parametrize(
    ("error", "kind", "model_kind"),
    [
        (UsageLimitExceeded("the request limit"), "rate_limit", ModelFailureKind.USAGE_LIMIT),
        (ModelHTTPError(status_code=401, model_name="m", body={"error": "bad key"}), "http_error", ModelFailureKind.REJECTED),
        (ModelHTTPError(status_code=503, model_name="m", body="down"), "http_error", ModelFailureKind.UNAVAILABLE),
        (UserError("a bad setting"), "http_error", ModelFailureKind.NOT_CONFIGURED),
        (UnexpectedModelBehavior("no text in the reply"), "model_error", ModelFailureKind.BAD_REPLY),
        (RuntimeError("a bug of the model adapter"), "model_error", ModelFailureKind.UNCLASSIFIED),
    ],
    ids=lambda value: value.value if isinstance(value, ModelFailureKind) else None,
)
async def test_extraction_error_kind_follows_the_failure_kind_of_the_model_call(monkeypatch, error, kind, model_kind):
    """The extraction reads `ModelCallFailed.kind`, never the class of an SDK error, and chains the cause."""

    def fails(_content) -> str:
        raise error

    install_fake_model(monkeypatch, fails)
    with pytest.raises(ExtractionError, match=f"^Extraction failed \\({kind}\\)") as raised:
        await ExtractionService()._extract_json_with_model(
            messages=[{"role": "user", "content": "Extract"}], model="test-vision-model"
        )
    assert isinstance(raised.value.__cause__, ModelCallFailed) and raised.value.__cause__.kind is model_kind


async def test_the_extraction_call_sends_the_settings_that_the_old_call_sent(monkeypatch):
    """Review of #3202: the role, the timeout, the attempts, the seed and the cap are the contract of the call."""
    sent = install_fake_model(monkeypatch, '{"institution": "DBS", "transactions": []}')
    await ExtractionService()._extract_json_with_model(
        messages=[{"role": "user", "content": "Extract"}], model="forced-model", seed_override=7
    )
    decoding = sent.decodings[0]
    assert (sent.roles, sent.models, sent.max_attempts, sent.extra_bodies[0]["do_sample"]) == (
        ["multimodal"],
        ["forced-model"],
        [2],
        False,
    )
    assert (decoding.timeout, decoding.seed, decoding.temperature) == (EXTRACTION_TIMEOUT_SECONDS, 7, 0.0)


@pytest.mark.parametrize("reply", ["[" * 100000, '{"a":' * 100000], ids=["arrays", "objects"])
async def test_a_reply_nested_too_deep_is_a_json_parse_error_not_a_recursion_error(monkeypatch, reply):
    """Review of #3202: `json.loads` raises RecursionError for 100000 nested brackets; the retry loop would not catch it."""
    install_fake_model(monkeypatch, reply)
    # The repair scan is not the subject here (it is slow on 100000 brackets): the parse is.
    monkeypatch.setattr(ExtractionService, "_repair_json_object", staticmethod(lambda _content: None))
    with pytest.raises(ExtractionError, match=r"^Extraction failed \(json_parse\)"):
        await ExtractionService()._extract_json_with_model(
            messages=[{"role": "user", "content": "Extract"}], model="test-vision-model"
        )


async def test_extract_json_timeout_and_ai_csv_empty(monkeypatch):
    service = ExtractionService()
    service.api_key = "test-key"

    def slow(_content):
        raise ModelTimeoutError("test-vision-model", "slow")

    install_fake_model(monkeypatch, slow)
    with pytest.raises(ExtractionError, match="Extraction failed \\(timeout\\): Model test-vision-model timed out"):
        await service._extract_json_with_model(
            messages=[{"role": "user", "content": "Extract"}], model="test-vision-model"
        )
    install_fake_model(monkeypatch, "  ")
    with pytest.raises(ModelCallFailed) as empty:
        await service._ai_parse_csv(
            headers=["Date", "Description", "Amount"],
            rows=[{"Date": "2026-01-01", "Description": "Test", "Amount": "1.00"}],
            institution="DBS",
            parse_date=date.fromisoformat,
            parse_amount=Decimal,
        )
    assert empty.value.kind is ModelFailureKind.BAD_REPLY


@pytest.mark.parametrize(
    ("side_effect", "payload", "match"),
    [
        (
            None,
            mock_statement_payload({"amount": "50.00", "direction": "IN", "description": "No date"}),
            "Transaction missing required fields",
        ),
        (
            None,
            mock_statement_payload(
                {"date": "invalid-date", "amount": "50.00", "direction": "IN", "description": "Bad"}
            ),
            "Transaction date",
        ),
        (
            None,
            mock_statement_payload({"date": True, "amount": "100.00", "direction": "IN", "description": "Bool"}),
            "Transaction date",
        ),
        (
            None,
            mock_statement_payload(
                {"date": "None", "amount": "50.00", "direction": "IN", "description": "N"},
                {"date": "null", "amount": "70.00", "direction": "IN", "description": "Null"},
            ),
            "Transaction date",
        ),
        (
            None,
            mock_statement_payload(
                {"date": "2023-01-15", "amount": "not-a-number", "direction": "IN", "description": "Bad"},
                closing="200.00",
            ),
            "Invalid transaction amount",
        ),
        (RuntimeError("Boom"), None, "Failed to parse document: Boom"),
    ],
)
async def test_parse_document_transaction_error_paths(side_effect, payload, match):
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(side_effect=side_effect, return_value=payload)
    with pytest.raises(ExtractionError, match=match):
        await service.parse_document(
            DocumentSource.resolve(path=Path("test.pdf"), content=b"content"), institution="DBS", user_id=uuid4()
        )


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
    assert (
        [row.description for row in result.transactions],
        result.transactions[0].direction,
        len({row.fact_id for row in result.transactions}),
    ) == (expected_descriptions, expected_direction, len(txns))


async def test_vision_paths_and_role_guards(monkeypatch):
    service = ExtractionService()
    service.api_key, service.multimodal_model = "test-key", "test-vision-model"
    mock_extract = AsyncMock(return_value={"transactions": []})
    service._extract_json_with_model = mock_extract
    image_payload = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
    with patch.object(service, "_build_vision_media_payload_batches", return_value=[[image_payload]]):
        assert await service.extract_financial_data(b"content", "DBS", "pdf") == {"transactions": []}
    assert (mock_extract.await_args.kwargs["model"], mock_extract.await_args.kwargs["messages"][0]["content"][1]) == (
        "test-vision-model",
        image_payload,
    )

    service.multimodal_model = ""
    sent = install_fake_model(monkeypatch, "{}")
    with (
        patch.object(service, "_build_vision_media_payload_batches") as bm,
        pytest.raises(ExtractionError, match="Multimodal model is not configured"),
    ):
        await service.extract_financial_data(file_content=b"content", institution="DBS", file_type="pdf")
    bm.assert_not_called()
    assert sent == []

    service = ExtractionService()
    service.api_key, service.multimodal_model = "test-key", "test-vision-model"

    def refuse(_content):
        raise ModelHTTPError(
            status_code=400,
            model_name="test-vision-model",
            body={"code": "1210", "message": "Invalid API parameter"},
        )

    sent = install_fake_model(monkeypatch, refuse)
    with (
        patch.object(service, "_build_vision_media_payload_batches", return_value=[[image_payload]]),
        pytest.raises(ExtractionError, match="Extraction failed \\(http_error\\): Model test-vision-model failed"),
    ):
        await service.extract_financial_data(b"content", "DBS", "pdf")
    assert (
        set(sent.models) == {"test-vision-model"}
        and 1 <= len(sent) <= 2
        and service.multimodal_model == "test-vision-model"
    )
    assert all(
        not hasattr(service, r)
        for r in (
            "ocr_model",
            "vision_model",
            "_vision_extraction_models",
            "_uses_dedicated_layout_ocr",
            "_extract_ocr_markdown",
            "_extract_json_with_models",
        )
    )
    with pytest.raises(ExtractionError, match="requires file content"):
        service._render_pdf_pages_as_image_payload_batches(b"")


@pytest.mark.parametrize(
    ("provider", "patch_target", "side_effect", "file_content", "file_url", "err_match"),
    [
        (
            "zai",
            "_build_ai_file_input",
            "data:application/pdf;base64,abc",
            None,
            "https://example.com/statement.pdf",
            "requires file content or an external PDF URL",
        ),
        (
            "zai",
            "_render_pdf_pages_as_image_payload_batches",
            ExtractionError("render failed"),
            b"pdf bytes",
            None,
            "render failed",
        ),
        (
            "gemini",
            "_render_pdf_pages_as_image_payload_batches",
            AssertionError("Gemini must not render PDF pages to images"),
            b"%PDF-1.4 fake pdf bytes",
            None,
            None,
        ),
    ],
)
def test_build_vision_media_payload_batches_variants(
    monkeypatch, provider, patch_target, side_effect, file_content, file_url, err_match
):
    monkeypatch.setattr(settings, "ai_provider", provider)
    service = ExtractionService()
    patch_kw = {"return_value": side_effect} if isinstance(side_effect, str) else {"side_effect": side_effect}
    with patch.object(service, patch_target, **patch_kw):
        if err_match:
            with pytest.raises(ExtractionError, match=err_match):
                service._build_vision_media_payload_batches(
                    file_content=file_content, file_url=file_url, file_type="pdf", mime_type="application/pdf"
                )
        else:
            batches = service._build_vision_media_payload_batches(
                file_content=file_content, file_url=file_url, file_type="pdf", mime_type="application/pdf"
            )
            assert (
                len(batches) == len(batches[0]) == 1
                and batches[0][0]["type"] == "file"
                and batches[0][0]["file"]["file_data"].startswith("data:application/pdf;base64,")
            )


def test_extraction_service_low_level_helpers():
    service = ExtractionService()
    assert (
        service._safe_decimal("1.23"),
        service._safe_decimal(None),
        service._safe_decimal(None, default="42.50"),
    ) == (Decimal("1.23"), None, Decimal("42.50"))
    for fn, arg, match in [
        (service._safe_decimal, "not-a-number", "Invalid decimal value"),
        (lambda x: service._safe_decimal(x, required=True), None, "Decimal value is required"),
        (service._safe_date, "not-a-date", "Invalid date format"),
        (service._safe_date, None, "Date is required"),
        (service._safe_date, "", "Date is required"),
    ]:
        with pytest.raises(ValueError, match=match):
            fn(arg)
    assert all(
        service._validate_external_url(u) is ok
        for u, ok in [
            ("http:///path", False),
            ("http://localhost:8000", False),
            ("http://192.168.1.1", False),
            ("http://minio:9000", False),
            ("https://google.com", True),
            ("not a url", False),
            (cast(str, None), False),
            (cast(str, object()), False),
        ]
    )
    assert service._build_media_payload(file_type="png", mime_type="image/png", data="data:image/png;base64,iVBOR") == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,iVBOR"},
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("553-3", "5533"),
        ("XXX-553-3", "5533"),
        (None, None),
        ("", None),
        ("12", "12"),
        ("---", None),
        ("1234", "1234"),
        ("12 34", "1234"),
        ("AB-12", "AB12"),
        ("ABCDEF1234", "1234"),
        ("12号34", "1234"),
        ("A", "A"),
    ],
)
def test_sanitize_account_last4(raw, expected):
    assert sanitize_account_last4(raw) == expected


async def test_parse_document_multicurrency_bank_balance_self_check_failure(test_user):
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "institution": "DBS",
            "account_last4": "0355",
            "currency": "SGD",
            "period_start": "2025-06-01",
            "period_end": "2025-06-30",
            # Scalar totals sum SGD+USD flows (1000 + 500 + 300 == 1800), so only per-currency validation catches USD mismatch.
            "opening_balance": "1000.00",
            "closing_balance": "1800.00",
            "balances": [
                {"currency": "SGD", "opening": "1000.00", "closing": "1500.00"},
                {"currency": "USD", "opening": "200.00", "closing": "400.00"},
            ],
            "transactions": [
                {
                    "date": "2025-06-10",
                    "description": "Salary",
                    "amount": "500.00",
                    "direction": "IN",
                    "currency": "SGD",
                },
                {
                    "date": "2025-06-12",
                    "description": "USD inflow",
                    "amount": "300.00",
                    "direction": "IN",
                    "currency": "USD",
                },
            ],
        }
    )
    res = await service.parse_document(
        DocumentSource.resolve(
            path=Path("dbs-statement-2506.pdf"),
            content=b"%PDF-1.7",
            content_hash="dbs-multicurrency-fail-hash",
            filename="dbs-statement-2506.pdf",
        ),
        institution="DBS",
        user_id=test_user.id,
    )
    assert (
        {b.currency for b in res.balances},
        res.balance_validated,
        res.transactions,
        any("llm_led_balance_chain_unreconciled" in reason for reason in res.review_reasons),
    ) == ({"SGD", "USD"}, False, (), True)


async def test_a_transient_model_error_is_retried_once_by_the_sdk(monkeypatch):
    """#3153: the SDK retries a server error of the model; the loop of passes is a different layer."""
    from pydantic_ai.exceptions import ModelServerError

    service = ExtractionService()
    service.api_key = "test-key"
    replies = iter([ModelServerError("m", "upstream"), '{"transactions": []}'])

    def answer(_content):
        outcome = next(replies)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    sent = install_fake_model(monkeypatch, answer)
    result = await service._extract_json_with_model(messages=[{"role": "user", "content": "x"}], model="test-model")
    assert result == {"transactions": []} and len(sent) == 2
