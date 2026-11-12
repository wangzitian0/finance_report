"""AC-extraction.retry-identity.1: a stalled parse is recovered from its run heartbeat, a live parse is not."""

from datetime import timedelta

from src.database import create_session_maker_from_db
from src.extraction import BankStatementStatus
from src.extraction.extension.statement_parsing_supervisor import reap_stale_parsing_runs
from tests.extraction.test_statement_parsing_supervisor import _running_statement


async def test_recovers_stalled_parsing_jobs(db, test_user):
    statement = await _running_statement(
        db, test_user, file_hash="hash-stuck", heartbeat_age=timedelta(seconds=200)
    )

    recovered_count = await reap_stale_parsing_runs(
        create_session_maker_from_db(db), stale_after=timedelta(seconds=180)
    )

    await db.refresh(statement)
    assert recovered_count == 1
    assert statement.status == BankStatementStatus.REJECTED
    assert "timed out" in statement.validation_error.lower()
    assert statement.confidence_score == 0
    assert statement.balance_validated is False


async def test_does_not_recover_fresh_parsing_jobs(db, test_user):
    statement = await _running_statement(
        db, test_user, file_hash="hash-fresh", heartbeat_age=timedelta(seconds=30)
    )

    recovered_count = await reap_stale_parsing_runs(
        create_session_maker_from_db(db), stale_after=timedelta(seconds=180)
    )

    await db.refresh(statement)
    assert recovered_count == 0
    assert statement.status == BankStatementStatus.PARSING
