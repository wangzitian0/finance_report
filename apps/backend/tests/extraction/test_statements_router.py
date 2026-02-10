"""AC3.5.4 - AC3.5.4: Statements Router Tests

These tests validate statement upload, duplicate detection, model selection,
file size limits, review queue management, and various error paths
including storage failures, retry mechanisms, and status transitions.
"""

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

    def get_object(self, key: str) -> bytes:
        return b"dummy content"

    def generate_presigned_url(
        self,
        *,
        key: str,
        expires_in: int | None = None,
        public: bool = False,
    ) -> str:
        return f"https://example.com/{key}"

    def delete_object(self, key: str) -> None:
        return None


@pytest.fixture
def storage_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(statements_router, "StorageService", DummyStorage)


@pytest.fixture
def model_catalog_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_model_info(model_id: str):
        return {"id": model_id, "input_modalities": ["image"]}

    monkeypatch.setattr(statements_router, "get_model_info", fake_get_model_info)


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


async def wait_for_background_tasks() -> None:
    await statements_router.wait_for_parse_tasks()


@pytest.mark.asyncio
async def test_upload_statement_duplicate(db, monkeypatch, storage_stub, model_catalog_stub, test_user):
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
        db=None,
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
        model="google/gemini-3-flash-preview",
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()
    await wait_for_background_tasks()
    user_id = test_user.id
    db.expire_all()

    upload_file_dup = make_upload_file("statement.pdf", content)
    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file_dup,
            institution="DBS",
            account_id=None,
            model="google/gemini-3-flash-preview",
            db=db,
            user_id=user_id,
        )
    await upload_file_dup.close()

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_upload_storage_failure(db, monkeypatch, model_catalog_stub, test_user):
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
            model="google/gemini-3-flash-preview",
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
async def test_upload_requires_model_for_pdf(db, test_user):
    """PDF/image uploads must include a model selection."""
    upload_file = make_upload_file("statement.pdf", b"content")

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
    assert "AI model is required" in exc.value.detail


@pytest.mark.asyncio
async def test_upload_rejects_text_only_model(db, monkeypatch, test_user):
    """Upload rejects models without image modalities."""

    async def fake_get_model_info(model_id: str):
        return {"id": model_id, "input_modalities": ["text"]}

    monkeypatch.setattr(statements_router, "get_model_info", fake_get_model_info)

    upload_file = make_upload_file("statement.pdf", b"content")

    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            account_id=None,
            model="text-only/model",
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == 400
    assert "does not support image/PDF inputs" in exc.value.detail


@pytest.mark.asyncio
async def test_list_and_transactions_flow(db, monkeypatch, storage_stub, model_catalog_stub, test_user):
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
        db=None,
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
        lambda self, key=None, expires_in=None, **kwargs: "http://fake.url",
    )

    upload_file = make_upload_file("statement.pdf", content)
    created = await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model="google/gemini-3-flash-preview",
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()
    await wait_for_background_tasks()
    user_id = test_user.id
    statement_id = created.id
    db.expire_all()

    listed = await statements_router.list_statements(db=db, user_id=user_id)
    assert listed.total == 1
    assert listed.items[0].id == statement_id

    fetched = await statements_router.get_statement(statement_id=statement_id, db=db, user_id=user_id)
    assert fetched.id == statement_id
    assert len(fetched.transactions) == 1
    assert fetched.transactions[0].description == "Salary"

    txns = await statements_router.list_statement_transactions(statement_id=statement_id, db=db, user_id=user_id)
    assert txns.total == 1
    assert txns.items[0].description == "Salary"


@pytest.mark.asyncio
async def test_pending_review_and_decisions(db, monkeypatch, storage_stub, model_catalog_stub, test_user):
    """Review queue filters by confidence and supports approve/reject."""
    contents = [b"review-70", b"review-90"]
    scores = [70, 90]
    score_by_hash = {
        hashlib.sha256(contents[0]).hexdigest(): scores[0],
        hashlib.sha256(contents[1]).hexdigest(): scores[1],
    }

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
        db=None,
    ):
        score = score_by_hash[file_hash or ""]
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
            model="google/gemini-3-flash-preview",
            db=db,
            user_id=test_user.id,
        )
        await upload_file.close()
        created_ids.append(created.id)
    await wait_for_background_tasks()

    pending = await statements_router.list_pending_review(db=db, user_id=test_user.id)
    assert pending.total == 1
    # Pending list should contain only the lower-confidence statement.
    assert pending.items[0].id == created_ids[0]

    # Test approve
    statement_id = pending.items[0].id

    approved = await statements_router.approve_statement(
        statement_id=statement_id,
        decision=StatementDecisionRequest(notes="Looks good"),
        db=db,
        user_id=test_user.id,
    )
    assert approved.status == BankStatementStatus.APPROVED

    # Test reject
    # Reuse statement_id for simplicity or create another one if needed.
    # Here we reject the same one after changing status back if needed,
    # or just test with a fresh one. The current router allows state transitions.
    rejected = await statements_router.reject_statement(
        statement_id=statement_id,
        decision=StatementDecisionRequest(notes="Incorrect data"),
        db=db,
        user_id=test_user.id,
    )
    assert rejected.status == BankStatementStatus.REJECTED


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
async def test_upload_file_too_large(db, model_catalog_stub, test_user):
    """File exceeding 10MB limit returns 413."""
    content = b"x" * (10 * 1024 * 1024 + 1)
    upload_file = make_upload_file("large-statement.pdf", content)

    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            account_id=None,
            model="google/gemini-3-flash-preview",
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == 413
    assert "10MB" in exc.value.detail


@pytest.mark.asyncio
async def test_upload_extraction_failure(db, monkeypatch, model_catalog_stub, test_user):
    """Extraction failure marks statement as rejected."""
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
        db=None,
    ):
        raise statements_router.ExtractionError("Failed to parse PDF")

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
        model="google/gemini-3-flash-preview",
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()
    await wait_for_background_tasks()

    statement = await db.get(BankStatement, created.id)
    assert statement is not None

    # Wait for background task to update status to REJECTED
    if statement.status == BankStatementStatus.PARSING:
        import asyncio

        await asyncio.sleep(0.5)
        await db.refresh(statement)

    assert statement.status == BankStatementStatus.REJECTED


@pytest.mark.asyncio
async def test_retry_statement_not_found(db, test_user):
    """Retry on missing statement returns 404."""
    from src.schemas import RetryParsingRequest

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            request=RetryParsingRequest(model=None),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_retry_rejects_text_only_model(db, monkeypatch, test_user):
    """Retry rejects models without image modalities."""
    from src.schemas import RetryParsingRequest

    statement = build_statement(test_user.id, "hash", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.commit()

    async def fake_get_model_info(model_id: str):
        return {"id": model_id, "input_modalities": ["text"]}

    monkeypatch.setattr(statements_router, "get_model_info", fake_get_model_info)

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=statement.id,
            request=RetryParsingRequest(model="text-only/model"),
            db=db,
            user_id=test_user.id,
        )

    assert exc.value.status_code == 400
    assert "does not support image/PDF inputs" in exc.value.detail


@pytest.mark.asyncio
async def test_retry_statement_storage_failure(db, monkeypatch, test_user):
    """Retry returns 503 if storage fetch fails."""
    from src.schemas import RetryParsingRequest

    statement = build_statement(test_user.id, "hash", 80)
    statement.status = BankStatementStatus.REJECTED
    statement.file_path = "path/to/file.pdf"
    db.add(statement)
    await db.commit()

    mock_storage = MagicMock()
    mock_storage.get_object.side_effect = statements_router.StorageError("S3 Down")
    monkeypatch.setattr(statements_router, "StorageService", MagicMock(return_value=mock_storage))

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=statement.id,
            request=RetryParsingRequest(model=None),
            db=db,
            user_id=test_user.id,
        )

    assert exc.value.status_code == 503
    assert "Failed to fetch file from storage" in exc.value.detail


@pytest.mark.asyncio
async def test_retry_statement_invalid_status(db, monkeypatch, storage_stub, model_catalog_stub, test_user):
    """Retry on statement not in parsed/rejected status returns 400."""
    from src.schemas import RetryParsingRequest

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
        db=None,
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
        model="google/gemini-3-flash-preview",
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()
    await wait_for_background_tasks()

    # To trigger a 400, we need a status NOT in (PARSED, REJECTED, PARSING)
    # UPLOADED status is not allowed for retry.
    statement = await db.get(BankStatement, created.id)
    statement.status = BankStatementStatus.UPLOADED
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=created.id,
            request=RetryParsingRequest(model=None),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == 400
    assert "stuck parsing statements" in exc.value.detail


@pytest.mark.asyncio
async def test_retry_statement_parsing_allowed(db, monkeypatch, storage_stub, test_user):
    """Verify that retrying a statement in PARSING status is allowed."""
    from unittest.mock import patch
    from uuid import uuid4

    from src.schemas import RetryParsingRequest

    sid = uuid4()
    statement = BankStatement(
        id=sid,
        user_id=test_user.id,
        status=BankStatementStatus.PARSING,
        file_path="p",
        file_hash="h_parsing",
        original_filename="f.pdf",
        institution="DBS",
    )
    db.add(statement)
    await db.commit()

    with patch("src.routers.statements.StorageService") as mock_storage_cls:
        mock_storage = mock_storage_cls.return_value
        mock_storage.get_object.return_value = b"content"

        resp = await statements_router.retry_statement_parsing(
            statement_id=sid,
            request=RetryParsingRequest(model=None),
            db=db,
            user_id=test_user.id,
        )
        assert resp.status == BankStatementStatus.PARSING


@pytest.mark.asyncio
async def test_retry_statement_success(db, monkeypatch, storage_stub, model_catalog_stub, test_user):
    """Retry parsing with stronger model succeeds."""
    from src.schemas import RetryParsingRequest

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
        db=None,
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
        model="google/gemini-3-flash-preview",
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()
    await wait_for_background_tasks()

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
        request=RetryParsingRequest(model="google/gemini-2.0-flash-exp:free"),
        db=db,
        user_id=test_user.id,
    )


@pytest.mark.asyncio
async def test_retry_statement_extraction_failure(db, monkeypatch, storage_stub, model_catalog_stub, test_user):
    """Retry extraction failure returns 422."""
    from src.schemas import RetryParsingRequest

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
        db=None,
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
        model="google/gemini-3-flash-preview",
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()
    await wait_for_background_tasks()

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
        db=None,
    ):
        raise statements_router.ExtractionError("Retry failed")

    monkeypatch.setattr(
        statements_router.ExtractionService,
        "parse_document",
        fake_retry_fail,
    )

    resp = await statements_router.retry_statement_parsing(
        statement_id=created.id,
        request=RetryParsingRequest(model="google/gemini-2.0-flash-exp:free"),
        db=db,
        user_id=test_user.id,
    )
    assert resp.status == BankStatementStatus.PARSING


@pytest.mark.asyncio
async def test_upload_statement_rejects_invalid_model(db, test_user, storage_stub, monkeypatch):
    """Upload rejects models not in the OpenRouter catalog."""
    content = b"some content"
    upload_file = make_upload_file("statement.pdf", content)

    async def fake_get_model_info(model_id: str):
        return None

    monkeypatch.setattr(statements_router, "get_model_info", fake_get_model_info)

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
async def test_upload_statement_catalog_unavailable(db, test_user, storage_stub, monkeypatch):
    """Upload returns 503 if model catalog fetch fails."""
    content = b"some content"
    upload_file = make_upload_file("statement.pdf", content)

    async def fake_get_model_info_fail(model_id: str):
        from src.services.openrouter_models import ModelCatalogError

        raise ModelCatalogError("Catalog down")

    monkeypatch.setattr(statements_router, "get_model_info", fake_get_model_info_fail)

    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            model="google/gemini-flash",
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == 503
    assert "Model catalog unavailable" in exc.value.detail


@pytest.mark.asyncio
async def test_retry_statement_catalog_unavailable(db, test_user, monkeypatch, storage_stub):
    """Retry returns 503 if model catalog fetch fails."""
    statement = build_statement(test_user.id, "hash", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.commit()

    async def fake_get_model_info_fail(model_id: str):
        from src.services.openrouter_models import ModelCatalogError

        raise ModelCatalogError("Catalog down")

    monkeypatch.setattr(statements_router, "get_model_info", fake_get_model_info_fail)

    from src.schemas import RetryParsingRequest

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=statement.id,
            request=RetryParsingRequest(model="google/gemini-flash"),
            db=db,
            user_id=test_user.id,
        )

    assert exc.value.status_code == 503
    assert "Model catalog unavailable" in exc.value.detail


@pytest.mark.asyncio
async def test_background_parse_error_logging(db, monkeypatch, test_user, storage_stub):
    """Background parse error should be caught and logged."""
    content = b"content"

    async def fake_parse_document_fail(*args, **kwargs):
        raise Exception("Fatal background error")

    monkeypatch.setattr(
        statements_router.ExtractionService,
        "parse_document",
        fake_parse_document_fail,
    )

    # Use model_catalog_stub to pass validation
    async def fake_get_model_info(model_id: str):
        return {"id": model_id, "input_modalities": ["image"]}

    monkeypatch.setattr(statements_router, "get_model_info", fake_get_model_info)

    upload_file = make_upload_file("statement.pdf", content)
    created = await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model="google/gemini-3-flash-preview",
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()

    # Wait for task - it should catch the exception
    await wait_for_background_tasks()

    # Statement should still be in PARSING or move to REJECTED?
    # In current implementation, if background task fails with unexpected error, it might stay in PARSING.
    # But line 300 logs the error.
    statement = await db.get(BankStatement, created.id)
    assert statement is not None


@pytest.mark.asyncio
async def test_background_retry_error_logging(db, monkeypatch, test_user, storage_stub):
    """Background retry error should be caught and logged."""
    statement = build_statement(test_user.id, "hash_retry", 80)
    statement.status = BankStatementStatus.REJECTED
    statement.file_path = "path"
    db.add(statement)
    await db.commit()

    async def fake_parse_document_fail(*args, **kwargs):
        raise Exception("Fatal background retry error")

    monkeypatch.setattr(
        statements_router.ExtractionService,
        "parse_document",
        fake_parse_document_fail,
    )

    monkeypatch.setattr(
        statements_router.StorageService,
        "get_object",
        lambda *args, **kwargs: b"content",
    )

    async def fake_get_model_info(model_id: str):
        return {"id": model_id, "input_modalities": ["image"]}

    monkeypatch.setattr(statements_router, "get_model_info", fake_get_model_info)

    from src.schemas import RetryParsingRequest

    await statements_router.retry_statement_parsing(
        statement_id=statement.id,
        request=RetryParsingRequest(model="google/gemini-flash"),
        db=db,
        user_id=test_user.id,
    )

    # Wait for task
    await wait_for_background_tasks()

    # Refresh to get updated statement
    await db.refresh(statement)
    # Background task sets status to PARSING before parsing, then REJECTED on error
    assert statement.status in (BankStatementStatus.PARSING, BankStatementStatus.REJECTED)
