"""Tests for statement router functions."""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, UploadFile

from src.models.statement import BankStatement, BankStatementStatus, BankStatementTransaction
from src.routers import statements as statements_router
from src.schemas import StatementDecisionRequest


class DummyStorage:
    """Storage stub for statement upload tests."""

    def upload_bytes(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> None:
        return None

    def generate_presigned_url(
        self,
        *,
        key: str,
        expires_in: int | None = None,
    ) -> str:
        return f"https://example.com/{key}"


@pytest.fixture
def storage_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(statements_router, "StorageService", DummyStorage)


def make_upload_file(name: str, content: bytes) -> UploadFile:
    """Create an UploadFile for testing."""
    return UploadFile(
        filename=name,
        file=BytesIO(content),
    )


def build_statement(user_id, file_hash: str, confidence_score: int) -> BankStatement:
    """Build a BankStatement model for tests."""
    return BankStatement(
        user_id=user_id,
        account_id=None,
        file_path="tmp",
        file_hash=file_hash,
        original_filename="stub.pdf",
        institution="DBS",
        account_last4="1234",
        currency="SGD",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("110.00"),
        status=BankStatementStatus.PARSED,
        confidence_score=confidence_score,
        balance_validated=True,
    )


@pytest.mark.asyncio
async def test_upload_statement_duplicate(db, monkeypatch, storage_stub, test_user):
    """Uploading the same file twice should trigger duplicate detection."""
    content = b"duplicate-statement"
    content = b"duplicate-statement"

    async def fake_parse_document(
        self,
        file_path,
        institution,
        user_id,
        file_type="pdf",
        account_id=None,
        file_content=None,
        file_hash=None,
        file_url=None,
        original_filename=None,
        force_model=None,
    ):
        statement = build_statement(test_user.id, file_hash or "", confidence_score=90)
        return statement, []

    monkeypatch.setattr(
        statements_router.ExtractionService,
        "parse_document",
        fake_parse_document,
    )

    upload_file = make_upload_file("statement.pdf", content)
    await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model=None,
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()

    upload_file_dup = make_upload_file("statement.pdf", content)
    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file_dup,
            institution="DBS",
            account_id=None,
            model=None,
            db=db,
            user_id=test_user.id,
        )
    await upload_file_dup.close()

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_upload_storage_failure(db, monkeypatch, test_user):
    """Storage failure should return 503."""
    content = b"content"

    # Mock StorageService to raise StorageError
    mock_storage = MagicMock()
    mock_storage.upload_bytes.side_effect = statements_router.StorageError("S3 Down")

    # We need to mock the class constructor to return our mock instance
    mock_storage_cls = MagicMock(return_value=mock_storage)
    monkeypatch.setattr(statements_router, "StorageService", mock_storage_cls)

    upload_file = make_upload_file("statement.pdf", content)

    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            account_id=None,
            model=None,
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == 503
    assert "S3 Down" in exc.value.detail


@pytest.mark.asyncio
async def test_upload_invalid_extension(db, test_user):
    """Invalid file extension should return 400."""
    content = b"content"
    upload_file = make_upload_file("statement.exe", content)

    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            account_id=None,
            model=None,
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == 400
    assert "Unsupported file type" in exc.value.detail


@pytest.mark.asyncio
async def test_list_and_transactions_flow(db, monkeypatch, storage_stub, test_user):
    """Upload then list statements and transactions."""
    content = b"statement-flow"
    hashlib.sha256(content).hexdigest()

    async def fake_parse_document(
        self,
        file_path,
        institution,
        user_id,
        file_type="pdf",
        account_id=None,
        file_content=None,
        file_hash=None,
        file_url=None,
        original_filename=None,
        force_model=None,
    ):
        statement = build_statement(test_user.id, file_hash or "", confidence_score=90)
        transaction = BankStatementTransaction(
            txn_date=date(2025, 1, 2),
            description="Salary",
            amount=Decimal("5000.00"),
            direction="IN",
        )
        return statement, [transaction]

    monkeypatch.setattr(
        statements_router.ExtractionService,
        "parse_document",
        fake_parse_document,
    )

    monkeypatch.setattr(
        statements_router.StorageService,
        "generate_presigned_url",
        lambda self, key=None, expires_in=None: "http://fake.url",
    )

    upload_file = make_upload_file("statement.pdf", content)
    created = await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model=None,
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()

    listed = await statements_router.list_statements(db=db, user_id=test_user.id)
    assert listed.total == 1
    assert listed.items[0].id == created.id

    fetched = await statements_router.get_statement(
        statement_id=created.id, db=db, user_id=test_user.id
    )
    assert fetched.id == created.id

    txns = await statements_router.list_statement_transactions(
        statement_id=created.id, db=db, user_id=test_user.id
    )
    assert txns.total == 1
    assert txns.items[0].description == "Salary"


@pytest.mark.asyncio
async def test_pending_review_and_decisions(db, monkeypatch, storage_stub, test_user):
    """Review queue filters by confidence and supports approve/reject."""
    contents = [b"review-70", b"review-90"]
    scores = [70, 90]

    async def fake_parse_document(
        self,
        file_path,
        institution,
        user_id,
        file_type="pdf",
        account_id=None,
        file_content=None,
        file_hash=None,
        file_url=None,
        original_filename=None,
        force_model=None,
    ):
        score = scores.pop(0)
        statement = build_statement(test_user.id, file_hash or "", confidence_score=score)
        return statement, []

    monkeypatch.setattr(
        statements_router.ExtractionService,
        "parse_document",
        fake_parse_document,
    )

    created_ids = []
    for index, content in enumerate(contents):
        upload_file = make_upload_file(f"statement-{index}.pdf", content)
        created = await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            account_id=None,
            model=None,
            db=db,
            user_id=test_user.id,
        )
        await upload_file.close()
        created_ids.append(created.id)

    pending = await statements_router.list_pending_review(db=db, user_id=test_user.id)
    assert pending.total == 1
    assert pending.items[0].confidence_score == 70

    approved = await statements_router.approve_statement(
        statement_id=created_ids[0],
        decision=StatementDecisionRequest(notes="Looks good"),
        db=db,
        user_id=test_user.id,
    )
    assert approved.status == BankStatementStatus.APPROVED
    assert approved.validation_error == "Looks good"

    rejected = await statements_router.reject_statement(
        statement_id=created_ids[1],
        decision=StatementDecisionRequest(notes="Reject this"),
        db=db,
        user_id=test_user.id,
    )
    assert rejected.status == BankStatementStatus.REJECTED
    assert rejected.validation_error == "Reject this"


@pytest.mark.asyncio
async def test_get_statement_not_found(db, test_user):
    """Missing statement returns 404."""
    with pytest.raises(HTTPException) as exc:
        await statements_router.get_statement(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_upload_file_too_large(db, test_user):
    """File exceeding 10MB limit returns 413."""
    content = b"x" * (10 * 1024 * 1024 + 1)
    upload_file = make_upload_file("large-statement.pdf", content)

    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            account_id=None,
            model=None,
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == 413
    assert "10MB" in exc.value.detail


@pytest.mark.asyncio
async def test_upload_extraction_failure(db, monkeypatch, test_user):
    """Extraction failure returns 422."""
    content = b"content"

    mock_storage = MagicMock()
    mock_storage.upload_bytes.return_value = None
    mock_storage.generate_presigned_url.return_value = "https://example.com/file"
    mock_storage_cls = MagicMock(return_value=mock_storage)
    monkeypatch.setattr(statements_router, "StorageService", mock_storage_cls)

    async def fake_parse_document(
        self,
        file_path,
        institution,
        user_id,
        file_type="pdf",
        account_id=None,
        file_content=None,
        file_hash=None,
        file_url=None,
        original_filename=None,
        force_model=None,
    ):
        raise statements_router.ExtractionError("Failed to parse PDF")

    monkeypatch.setattr(
        statements_router.ExtractionService,
        "parse_document",
        fake_parse_document,
    )

    upload_file = make_upload_file("statement.pdf", content)

    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            account_id=None,
            model=None,
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == 422
    assert "Failed to parse PDF" in exc.value.detail


@pytest.mark.asyncio
async def test_retry_statement_not_found(db, test_user):
    """Retry on missing statement returns 404."""
    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            model=None,
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_retry_statement_invalid_status(db, monkeypatch, storage_stub, test_user):
    """Retry on statement not in parsed/rejected status returns 400."""
    content = b"statement"

    async def fake_parse_document(
        self,
        file_path,
        institution,
        user_id,
        file_type="pdf",
        account_id=None,
        file_content=None,
        file_hash=None,
        file_url=None,
        original_filename=None,
        force_model=None,
    ):
        statement = build_statement(test_user.id, file_hash or "", confidence_score=90)
        statement.status = BankStatementStatus.PARSING
        return statement, []

    monkeypatch.setattr(
        statements_router.ExtractionService,
        "parse_document",
        fake_parse_document,
    )

    upload_file = make_upload_file("statement.pdf", content)
    created = await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model=None,
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=created.id,
            model=None,
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == 400
    assert "parsed or rejected" in exc.value.detail


@pytest.mark.asyncio
async def test_retry_statement_success(db, monkeypatch, storage_stub, test_user):
    """Retry parsing with stronger model succeeds."""
    content = b"statement"

    async def fake_parse_document(
        self,
        file_path,
        institution,
        user_id,
        file_type="pdf",
        account_id=None,
        file_content=None,
        file_hash=None,
        file_url=None,
        original_filename=None,
        force_model=None,
    ):
        statement = build_statement(test_user.id, file_hash or "", confidence_score=95)
        statement.status = BankStatementStatus.REJECTED
        statement.confidence_score = 60
        return statement, []

    monkeypatch.setattr(
        statements_router.ExtractionService,
        "parse_document",
        fake_parse_document,
    )

    upload_file = make_upload_file("statement.pdf", content)
    created = await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model=None,
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()

    rejected = await statements_router.reject_statement(
        statement_id=created.id,
        decision=StatementDecisionRequest(notes="Low confidence"),
        db=db,
        user_id=test_user.id,
    )
    assert rejected.status == BankStatementStatus.REJECTED

    mock_parse = AsyncMock()
    monkeypatch.setattr(
        statements_router.ExtractionService,
        "parse_document",
        mock_parse,
    )

    mock_statement = build_statement(test_user.id, "", confidence_score=95)
    mock_parse.return_value = (mock_statement, [])

    await statements_router.retry_statement_parsing(
        statement_id=created.id,
        model="google/gemini-2.0-flash-exp:free",
        db=db,
        user_id=test_user.id,
    )

    mock_parse.assert_called_once()
    call_kwargs = mock_parse.call_args
    assert call_kwargs.kwargs.get("force_model") == "google/gemini-2.0-flash-exp:free"

    async def fake_retry(
        self,
        file_path,
        institution,
        user_id,
        file_type="pdf",
        account_id=None,
        file_content=None,
        file_hash=None,
        file_url=None,
        original_filename=None,
        force_model=None,
    ):
        statement = build_statement(test_user.id, file_hash or "", confidence_score=95)
        return statement, []

    monkeypatch.setattr(
        statements_router.ExtractionService,
        "parse_document",
        fake_retry,
    )

    retried = await statements_router.retry_statement_parsing(
        statement_id=created.id,
        model="google/gemini-2.0-flash-exp:free",
        db=db,
        user_id=test_user.id,
    )
    assert retried.status == BankStatementStatus.PARSED
    assert retried.confidence_score == 95


@pytest.mark.asyncio
async def test_retry_statement_extraction_failure(db, monkeypatch, storage_stub, test_user):
    """Retry extraction failure returns 422."""
    content = b"statement"

    async def fake_parse_document(
        self,
        file_path,
        institution,
        user_id,
        file_type="pdf",
        account_id=None,
        file_content=None,
        file_hash=None,
        file_url=None,
        original_filename=None,
        force_model=None,
    ):
        statement = build_statement(test_user.id, file_hash or "", confidence_score=90)
        statement.status = BankStatementStatus.REJECTED
        return statement, []

    monkeypatch.setattr(
        statements_router.ExtractionService,
        "parse_document",
        fake_parse_document,
    )

    upload_file = make_upload_file("statement.pdf", content)
    created = await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model=None,
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()

    rejected = await statements_router.reject_statement(
        statement_id=created.id,
        decision=StatementDecisionRequest(notes="Low confidence"),
        db=db,
        user_id=test_user.id,
    )
    assert rejected.status == BankStatementStatus.REJECTED

    async def fake_retry_fail(
        self,
        file_path,
        institution,
        user_id,
        file_type="pdf",
        account_id=None,
        file_content=None,
        file_hash=None,
        file_url=None,
        original_filename=None,
        force_model=None,
    ):
        raise statements_router.ExtractionError("Retry failed")

    monkeypatch.setattr(
        statements_router.ExtractionService,
        "parse_document",
        fake_retry_fail,
    )

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=created.id,
            model="google/gemini-2.0-flash-exp:free",
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == 422
    assert "Retry failed" in exc.value.detail


@pytest.mark.asyncio
async def test_upload_statement_with_invalid_model(db, test_user, storage_stub, monkeypatch):
    """Test upload with an invalid model selection."""
    content = b"some content"
    upload_file = make_upload_file("statement.pdf", content)

    mock_fetch = AsyncMock(return_value=[{"id": "known/model"}])
    monkeypatch.setattr(statements_router, "fetch_model_catalog", mock_fetch)
    monkeypatch.setattr(statements_router.settings, "primary_model", "default/model")
    monkeypatch.setattr(statements_router.settings, "fallback_models", ["fallback/model"])

    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            model="unknown/model",
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == 400
    assert "Invalid model selection" in exc.value.detail


@pytest.mark.asyncio
async def test_upload_statement_with_model_catalog_unavailable(
    db, test_user, storage_stub, monkeypatch
):
    """Test upload when model catalog is unavailable."""
    content = b"some content"
    upload_file = make_upload_file("statement.pdf", content)

    mock_fetch = AsyncMock(side_effect=Exception("catalog down"))
    monkeypatch.setattr(statements_router, "fetch_model_catalog", mock_fetch)
    monkeypatch.setattr(statements_router.settings, "primary_model", "default/model")
    monkeypatch.setattr(statements_router.settings, "fallback_models", ["fallback/model"])

    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            model="any/model",
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == 503
    assert "Unable to validate" in exc.value.detail


@pytest.mark.asyncio
async def test_upload_statement_with_unsupported_modality(db, test_user, storage_stub, monkeypatch):
    """Test upload with a model that does not support the file's modality."""
    content = b"some content"
    upload_file = make_upload_file("statement.pdf", content)  # pdf is treated as image

    mock_fetch = AsyncMock(return_value=[{"id": "text-model", "name": "Text Model"}])
    monkeypatch.setattr(statements_router, "fetch_model_catalog", mock_fetch)

    mock_modality_match = MagicMock(return_value=False)
    monkeypatch.setattr(statements_router, "model_matches_modality", mock_modality_match)
    monkeypatch.setattr(statements_router.settings, "primary_model", "default/model")
    monkeypatch.setattr(statements_router.settings, "fallback_models", ["fallback/model"])

    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            model="text-model",
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == 400
    assert "does not support image inputs" in exc.value.detail


@pytest.mark.asyncio
async def test_retry_statement_with_invalid_model(db, test_user, monkeypatch):
    """Test retry with an invalid model selection."""
    statement = build_statement(test_user.id, "hash", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.commit()

    mock_fetch = AsyncMock(return_value=[{"id": "known/model"}])
    monkeypatch.setattr(statements_router, "fetch_model_catalog", mock_fetch)
    monkeypatch.setattr(statements_router.settings, "primary_model", "default/model")
    monkeypatch.setattr(statements_router.settings, "fallback_models", ["fallback/model"])

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=statement.id,
            model="unknown/model",
            db=db,
            user_id=test_user.id,
        )

    assert exc.value.status_code == 400
    assert "Invalid model selection" in exc.value.detail


@pytest.mark.asyncio
async def test_retry_statement_with_model_catalog_unavailable(db, test_user, monkeypatch):
    """Test retry when model catalog is unavailable."""
    statement = build_statement(test_user.id, "hash", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.commit()

    mock_fetch = AsyncMock(side_effect=Exception("catalog down"))
    monkeypatch.setattr(statements_router, "fetch_model_catalog", mock_fetch)
    monkeypatch.setattr(statements_router.settings, "primary_model", "default/model")
    monkeypatch.setattr(statements_router.settings, "fallback_models", ["fallback/model"])

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=statement.id,
            model="any/model",
            db=db,
            user_id=test_user.id,
        )

    assert exc.value.status_code == 503
    assert "Unable to validate" in exc.value.detail


@pytest.mark.asyncio
async def test_retry_statement_with_unsupported_modality(db, test_user, monkeypatch):
    """Test retry with a model that does not support the file's modality."""
    statement = build_statement(test_user.id, "hash", 80)
    statement.status = BankStatementStatus.REJECTED
    statement.original_filename = "image.png"
    db.add(statement)
    await db.commit()

    mock_fetch = AsyncMock(return_value=[{"id": "text-model", "name": "Text Model"}])
    monkeypatch.setattr(statements_router, "fetch_model_catalog", mock_fetch)

    mock_modality_match = MagicMock(return_value=False)
    monkeypatch.setattr(statements_router, "model_matches_modality", mock_modality_match)
    monkeypatch.setattr(statements_router.settings, "primary_model", "default/model")
    monkeypatch.setattr(statements_router.settings, "fallback_models", ["fallback/model"])

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=statement.id,
            model="text-model",
            db=db,
            user_id=test_user.id,
        )

    assert exc.value.status_code == 400
    assert "does not support image inputs" in exc.value.detail
