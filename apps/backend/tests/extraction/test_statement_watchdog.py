"""AC-extraction.retry-identity.1: Tests for statement parsing watchdog recovery."""

from datetime import UTC, datetime, timedelta

from src.extraction import BankStatementStatus
from src.extraction.extension.statement_pipeline import check_and_recover_stalled_parsing_jobs
from tests.factories import StatementSummaryFactory


async def test_recovers_stalled_parsing_jobs(db, test_user):
    """Statements stuck in parsing longer than threshold are recovered to REJECTED."""
    stale_time = datetime.now(UTC) - timedelta(seconds=200)
    statement = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=None,
        file_hash="hash-stuck",
        institution="MariBank",
        status=BankStatementStatus.PARSING,
        confidence_score=None,
        balance_validated=None,
    )
    statement.updated_at = stale_time
    db.add(statement)
    await db.commit()

    recovered_ids = await check_and_recover_stalled_parsing_jobs(db, stall_threshold_seconds=180)
    await db.refresh(statement)

    assert str(statement.id) in [str(rid) for rid in recovered_ids]
    assert statement.status == BankStatementStatus.REJECTED
    assert "timed out" in statement.validation_error.lower()
    assert statement.confidence_score == 0
    assert statement.balance_validated is False


async def test_does_not_recover_fresh_parsing_jobs(db, test_user):
    """Statements actively parsing within threshold remain untouched."""
    fresh_time = datetime.now(UTC) - timedelta(seconds=30)
    statement = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=None,
        file_hash="hash-fresh",
        institution="MariBank",
        status=BankStatementStatus.PARSING,
        confidence_score=None,
        balance_validated=None,
    )
    statement.updated_at = fresh_time
    db.add(statement)
    await db.commit()

    recovered_ids = await check_and_recover_stalled_parsing_jobs(db, stall_threshold_seconds=180)
    await db.refresh(statement)

    assert str(statement.id) not in [str(rid) for rid in recovered_ids]
    assert statement.status == BankStatementStatus.PARSING
