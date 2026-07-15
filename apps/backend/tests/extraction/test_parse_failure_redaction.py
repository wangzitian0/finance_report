"""Parse-failure text is PII-redacted before persistence/logging (#1864 S1).

AC-observability.safe-error-ssot.2: ``handle_parse_failure`` routes the failure
message through ``safe_error_message`` for both the ``validation_error`` column
and the failure-log fields, so an exception message quoting statement content
(emails, account numbers) never lands raw.
"""

from src.extraction.extension.statement_parsing import handle_parse_failure
from src.extraction.orm.statement_enums import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary
from tests.factories import StatementSummaryFactory, UploadedDocumentFactory

PII_MESSAGE = "Failed to parse row 12: unexpected value for john.doe@example.com (account 123456789012)"


async def test_AC_safe_error_ssot_2_handle_parse_failure_redacts_pii(db, test_user):
    """AC-observability.safe-error-ssot.2: validation_error is redacted and bounded."""
    doc = await UploadedDocumentFactory.create_async(db, user_id=test_user.id)
    summary = await StatementSummaryFactory.create_async(
        db,
        user_id=test_user.id,
        uploaded_document_id=doc.id,
        file_hash=doc.file_hash,
    )
    await db.commit()

    await handle_parse_failure(
        summary,
        db,
        message=PII_MESSAGE,
        statement_id=summary.id,
        error_type="ValueError",
    )

    refreshed = await db.get(StatementSummary, summary.id)
    assert refreshed is not None
    assert refreshed.status == BankStatementStatus.REJECTED
    stored = refreshed.validation_error or ""
    assert stored, "failure message must be persisted for the rejection reason"
    assert "john.doe@example.com" not in stored, "raw email persisted to validation_error"
    assert "123456789012" not in stored, "raw account number persisted to validation_error"
    assert "[EMAIL]" in stored, "redaction label missing — message did not go through safe_error_message"
