"""Tests for statement router functions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from src.models.statement import BankStatement, BankStatementStatus
from src.routers import statements as statements_router


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
async def test_get_nonexistent_statement(db, test_user):
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
            model="google/gemini-flash",
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == 413
    assert "10MB" in exc.value.detail


@pytest.mark.asyncio
async def test_retry_nonexistent_statement(db, test_user):
    """Retry on missing statement returns 404."""
    from src.schemas import RetryParsingRequest

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            request=RetryParsingRequest(model="google/gemini-flash"),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == 404
