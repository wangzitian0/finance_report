"""Tests for statement router functions."""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, UploadFile

from src.models.statement import (
    BankStatement,
    BankStatementStatus,
    BankStatementTransaction,
)
from src.routers import statements as statements_router
from src.schemas import StatementDecisionRequest


class DummyStorage:
    """Storage stub for statement upload tests."""

    def upload_bytes(self, *, key, content, content_type=None):  # noqa: ANN001
        return None

    def generate_presigned_url(self, *, key, expires_in=None):  # noqa: ANN001
        return f"https://example.com/{key}"


@pytest.fixture
def storage_stub(monkeypatch):
    monkeypatch.setattr(statements_router, "StorageService", DummyStorage)


def make_upload_file(name: str, content: bytes) -> UploadFile:
    """Create an UploadFile for testing."""
    return UploadFile(
        filename=name,
        file=BytesIO(content),
    )


def build_statement(file_hash: str, confidence_score: int) -> BankStatement:
    """Build a BankStatement model for tests."""
    return BankStatement(
        user_id=statements_router.MOCK_USER_ID,
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
async def test_upload_statement_duplicate(db, monkeypatch, storage_stub):
    """Uploading the same file twice should trigger duplicate detection."""
    content = b"duplicate-statement"
    file_hash = hashlib.sha256(content).hexdigest()

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
    ):
        statement = build_statement(file_hash or "", confidence_score=90)
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
        db=db,
    )
    await upload_file.close()

    upload_file_dup = make_upload_file("statement.pdf", content)
    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file_dup,
            institution="DBS",
            account_id=None,
            db=db,
        )
    await upload_file_dup.close()

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_upload_storage_failure(db, monkeypatch):
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
            db=db,
        )
    await upload_file.close()

    assert exc.value.status_code == 503
    assert "S3 Down" in exc.value.detail


@pytest.mark.asyncio
async def test_upload_invalid_extension(db):
    """Invalid file extension should return 400."""
    content = b"content"
    upload_file = make_upload_file("statement.exe", content)
    
    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            account_id=None,
            db=db,
        )
    await upload_file.close()

    assert exc.value.status_code == 400
    assert "Unsupported file type" in exc.value.detail


@pytest.mark.asyncio
async def test_list_and_transactions_flow(db, monkeypatch, storage_stub):
    """Upload then list statements and transactions."""
    content = b"statement-flow"
    file_hash = hashlib.sha256(content).hexdigest()

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
    ):
        statement = build_statement(file_hash or "", confidence_score=90)
        transaction = BankStatementTransaction(
            txn_date=date(2025, 1, 2),
            description="Salary",
            amount=Decimal("10.00"),
            direction="IN",
        )
        return statement, [transaction]

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
        db=db,
    )
    await upload_file.close()

    listed = await statements_router.list_statements(db=db)
    assert listed.total == 1
    assert listed.items[0].id == created.id

    fetched = await statements_router.get_statement(statement_id=created.id, db=db)
    assert fetched.id == created.id

    txns = await statements_router.list_statement_transactions(
        statement_id=created.id, db=db
    )
    assert txns.total == 1
    assert txns.items[0].description == "Salary"


@pytest.mark.asyncio
async def test_pending_review_and_decisions(db, monkeypatch, storage_stub):
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
    ):
        score = scores.pop(0)
        statement = build_statement(file_hash or "", confidence_score=score)
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
            db=db,
        )
        await upload_file.close()
        created_ids.append(created.id)

    pending = await statements_router.list_pending_review(db=db)
    assert pending.total == 1
    assert pending.items[0].confidence_score == 70

    approved = await statements_router.approve_statement(
        statement_id=created_ids[0],
        decision=StatementDecisionRequest(notes="Looks good"),
        db=db,
    )
    assert approved.status == BankStatementStatus.APPROVED
    assert approved.validation_error == "Looks good"

    rejected = await statements_router.reject_statement(
        statement_id=created_ids[1],
        decision=StatementDecisionRequest(notes="Reject this"),
        db=db,
    )
    assert rejected.status == BankStatementStatus.REJECTED
    assert rejected.validation_error == "Reject this"


@pytest.mark.asyncio
async def test_get_statement_not_found(db):
    """Missing statement returns 404."""
    with pytest.raises(HTTPException) as exc:
        await statements_router.get_statement(
            statement_id=statements_router.UUID(
                "00000000-0000-0000-0000-000000000000"
            ),
            db=db,
        )
    assert exc.value.status_code == 404
