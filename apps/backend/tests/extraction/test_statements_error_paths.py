from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.extraction import BankStatementStatus, ParseJob
from src.extraction.extension.statement_parsing import handle_parse_failure
from src.extraction.orm.statement_summary import StatementSummary
from src.observability.pii_redaction import PIIType, detect_pii
from tests.factories import StatementSummaryFactory, UploadedDocumentFactory
from tests.statement_ingestion import run_for

PII_MESSAGE = "Failed to parse row 12: unexpected value for john.doe@example.com (account 123456789012)"


async def _create_parsing_statement(db, user_id, file_hash: str):
    return await StatementSummaryFactory.create_async(
        db, user_id, file_hash=file_hash, institution="TEST", account_last4="1234", currency="SGD",
        period_start=date(2025, 1, 1), period_end=date(2025, 1, 31),
        opening_balance=Decimal("100.00"), closing_balance=Decimal("100.00"),
        status=BankStatementStatus.PARSING, confidence_score=0, balance_validated=False,
    )


async def test_handle_parse_failure_error_paths(db, test_user):
    stmt1 = await _create_parsing_statement(db, test_user.id, "abc123_1")
    await db.commit()
    with patch.object(db, "rollback", side_effect=SQLAlchemyError("Rollback failed")):
        await handle_parse_failure(db=db, statement=stmt1, message="Test error")
    await db.refresh(stmt1)
    assert (stmt1.status, stmt1.validation_error) == (BankStatementStatus.REJECTED, "Test error")

    stmt2 = await _create_parsing_statement(db, test_user.id, "abc123_2")
    await db.commit()
    sid2 = stmt2.id
    await db.delete(stmt2)
    await db.commit()
    await handle_parse_failure(db=db, statement=MagicMock(id=sid2), message="Test error")

    stmt3 = await _create_parsing_statement(db, test_user.id, "abc123_3")
    await db.commit()
    orig_commit = db.commit

    async def failing_commit():
        if not hasattr(failing_commit, "called"):
            failing_commit.called = True
            await orig_commit()
        else:
            raise SQLAlchemyError("Commit failed")

    with patch.object(db, "commit", side_effect=failing_commit):
        await handle_parse_failure(db=db, statement=stmt3, message="Test error")


async def test_AC_safe_error_ssot_2_handle_parse_failure_redacts_pii(db, test_user):
    doc = await UploadedDocumentFactory.create_async(db, user_id=test_user.id)
    summary = await StatementSummaryFactory.create_async(db, user_id=test_user.id, uploaded_document_id=doc.id, file_hash=doc.file_hash, status=BankStatementStatus.PARSING)
    await db.commit()
    await handle_parse_failure(
        summary, db,
        job=ParseJob(statement_id=summary.id, run_id=await run_for(db, summary.id), filename=doc.original_filename, institution=summary.institution, user_id=test_user.id, account_id=summary.account_id, file_hash=summary.file_hash, storage_key=doc.file_path, model=None),
        message=PII_MESSAGE, error_type="ValueError",
    )
    refreshed = await db.get(StatementSummary, summary.id)
    stored = (refreshed.validation_error or "") if refreshed else ""
    assert refreshed is not None and refreshed.status == BankStatementStatus.REJECTED and stored and "john.doe@example.com" not in stored and "123456789012" not in stored and "[EMAIL]" in stored


@pytest.mark.parametrize(
    ("text", "pii_type", "count", "first"),
    [
        ("Customer: John Doe, NRIC: S1234567A", PIIType.NRIC, 1, "S1234567A"),
        ("S1234567A G9876543Z T0123456B F7654321X M1111111A", PIIType.NRIC, 5, "S1234567A"),
        ("Contact: user@example.com for support", PIIType.EMAIL, 1, "user@example.com"),
        ("Call +65 91234567 or 65 81234567", PIIType.PHONE, 2, None),
        ("Mobile: 91234567", PIIType.PHONE, 1, None),
        ("Address: 123 Main St, Singapore 518000", PIIType.POSTAL_CODE, 1, "518000"),
        ("Account: 1234567890", PIIType.BANK_ACCOUNT, 1, None),
        ("Date: 20250115", PIIType.BANK_ACCOUNT, 0, None),
    ],
)
def test_detect_pii(text, pii_type, count, first):
    matches = [m for m in detect_pii(text) if m.pii_type == pii_type]
    assert (len(matches) >= count if pii_type == PIIType.PHONE and count > 1 else len(matches) == count) and (first is None or matches[0].original == first)
    assert detect_pii("") == [] and not [m for m in detect_pii("Transaction: SALARY DEPOSIT 5000.00 SGD") if m.pii_type in (PIIType.NRIC, PIIType.EMAIL)]
