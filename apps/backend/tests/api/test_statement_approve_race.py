"""Approve against a rerun, and a parse failure against an approved statement (#2994, slice S2 review).

A rerun commits the status PARSING and an active run. An approve that read the statement before that
commit must not post entries on top of it. The statement and the ledger must agree.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select, update

from src.composition import compose_statement_posting_dependencies
from src.database import create_session_maker_from_db
from src.extraction import (
    BankStatementStatus,
    ActiveRunExists,
    ParseJob,
    RunActorKind,
    RunHints,
    RunKind,
    RunState,
    RunTrigger,
    StatementSummary,
    TransactionDirection,
    claim_run,
    create_run,
    finish_run,
)
from src.extraction.extension.statement_parsing import handle_parse_failure
from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement
from src.extraction.orm.statement_run import StatementRun
from src.ledger import JournalEntry
from src.routers import statements as statements_router
from tests.api._statement_router_fixtures import create_statement_account
from tests.factories import seed_parsed_statement
from tests.integration.test_statement_corpus_journeys import attach_reviewed_corpus_semantics

CSV_FOR_WORKER = (
    b"Statement Currency,Date,Description,Debit Amount,Credit Amount\n"
    b"SGD,2026-01-05,Salary,,5000.00\n"
)
ROWS = [
    {"description": "Salary Jan", "amount": Decimal("2500.00"), "direction": TransactionDirection.IN, "date": date(2026, 1, 5)},
    {"description": "Rent Jan", "amount": Decimal("12.50"), "direction": TransactionDirection.OUT, "date": date(2026, 1, 6)},
]


async def _approvable_statement(db, user):
    seeded = await seed_parsed_statement(
        db, user.id, institution="DBS", original_filename="race.pdf", opening_balance=Decimal("1000.00"), transactions=ROWS
    )
    seeded.document.file_path = "statements/race.pdf"
    seeded.statement.account_last4 = "1234"
    seeded.statement.period_start = ROWS[0]["date"]
    seeded.statement.period_end = ROWS[-1]["date"]
    await attach_reviewed_corpus_semantics(db, user.id, seeded.transactions)
    # The custody account is bound up front: the route then writes nothing to the statement row before the
    # approve, so a rerun of another tab can commit in that window.
    seeded.statement.account_id = (await create_statement_account(db, user.id)).id
    await db.commit()
    return seeded.id


async def _entry_count(db, user) -> int:
    return await db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == user.id))


async def _fresh(db, statement_id) -> StatementSummary:
    return await db.scalar(
        select(StatementSummary).where(StatementSummary.id == statement_id).execution_options(populate_existing=True)
    )


async def test_AC_extraction_2994_83_a_normal_approve_of_a_parsed_statement_still_posts(client, db, test_user):
    """AC-extraction.2994.83: Approve of a PARSED statement works: it posts its entries and sets APPROVED."""
    statement_id = await _approvable_statement(db, test_user)

    response = await client.post(f"/statements/{statement_id}/review/approve", json={})

    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == len(ROWS)
    assert await _entry_count(db, test_user) >= len(ROWS), "one entry for each row, and the opening balance"
    assert (await _fresh(db, statement_id)).status is BankStatementStatus.APPROVED


async def test_AC_extraction_2994_83_an_approve_after_a_committed_rerun_posts_nothing(
    client, db, monkeypatch, test_user
):
    """AC-extraction.2994.83: Approve sees the committed PARSING under its lock: no entry is posted, the status stays."""
    statement_id = await _approvable_statement(db, test_user)
    maker = create_session_maker_from_db(db)
    original = statements_router.approve_statement_workflow
    rerun_ids: list = []

    async def approve_after_a_rerun(*args, **kwargs):
        # The route read PARSED. Another tab now commits a rerun: the run and the status PARSING.
        async with maker() as other_tab:
            rerun = await create_run(
                other_tab,
                statement_id=statement_id,
                user_id=test_user.id,
                kind=RunKind.EXTRACT,
                actor_kind=RunActorKind.USER,
                trigger=RunTrigger.RERUN,
                hints=RunHints(),
            )
            rerun_ids.append(rerun.id)
            await other_tab.execute(
                update(StatementSummary).where(StatementSummary.id == statement_id).values(status=BankStatementStatus.PARSING)
            )
            await other_tab.commit()
        return await original(*args, **kwargs)

    monkeypatch.setattr(statements_router, "approve_statement_workflow", approve_after_a_rerun)

    response = await client.post(f"/statements/{statement_id}/review/approve", json={})

    assert response.status_code == 409, response.text
    assert response.json()["active_run_id"] == str(rerun_ids[0])
    assert await _entry_count(db, test_user) == 0, "the approve must post nothing on a statement that parses again"
    assert (await _fresh(db, statement_id)).status is BankStatementStatus.PARSING
    runs = (await db.execute(select(StatementRun).where(StatementRun.statement_id == statement_id))).scalars().all()
    assert [run.state for run in runs] == [RunState.REQUESTED]


async def test_AC_extraction_2994_84_a_parse_failure_leaves_an_approved_statement_and_its_entries(
    client, db, test_user
):
    """AC-extraction.2994.84: The failure handler writes the final status only while the statement is PARSING."""
    statement_id = await _approvable_statement(db, test_user)
    approved = await client.post(f"/statements/{statement_id}/review/approve", json={})
    assert approved.status_code == 200, approved.text
    entries_before = await _entry_count(db, test_user)
    statement = await _fresh(db, statement_id)
    file_hash, error_before = statement.file_hash, statement.validation_error
    run = await create_run(
        db,
        statement_id=statement_id,
        user_id=test_user.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.USER,
        trigger=RunTrigger.RERUN,
        hints=RunHints(),
    )
    await claim_run(db, run.id)
    await db.commit()
    job = ParseJob(
        statement_id=statement_id,
        run_id=run.id,
        filename="race.pdf",
        institution="DBS",
        user_id=test_user.id,
        account_id=None,
        file_hash=file_hash,
        storage_key="statements/race.pdf",
        model=None,
        request_id="req-race",
    )
    maker = create_session_maker_from_db(db)

    async with maker() as session:
        parsed = await session.get(StatementSummary, statement_id)
        await handle_parse_failure(
            parsed, session, job=job, message="The parse failed.", error_type="ExtractionError"
        )

    after = await _fresh(db, statement_id)
    assert after.status is BankStatementStatus.APPROVED, "a failed parse must not reject an approved statement"
    assert after.validation_error == error_before
    assert await _entry_count(db, test_user) == entries_before
    failed = await db.scalar(
        select(StatementRun).where(StatementRun.id == run.id).execution_options(populate_existing=True)
    )
    assert failed.state is RunState.FAILED, "the run still ends as failed"


async def _running_run(db, statement_id, user):
    run = await create_run(
        db,
        statement_id=statement_id,
        user_id=user.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.USER,
        trigger=RunTrigger.RERUN,
        hints=RunHints(),
    )
    await claim_run(db, run.id)
    await db.commit()
    return run.id


async def test_AC_extraction_2994_87_an_approve_refuses_a_statement_with_an_active_run(client, db, test_user):
    """AC-extraction.2994.87: Approve refuses an active run, also when the statement still says PARSED."""
    statement_id = await _approvable_statement(db, test_user)
    run_id = await _running_run(db, statement_id, test_user)  # The state that a stale envelope confirmation left behind.

    response = await client.post(f"/statements/{statement_id}/review/approve", json={})

    assert response.status_code == 409, response.text
    assert response.json()["active_run_id"] == str(run_id)
    assert await _entry_count(db, test_user) == 0
    assert (await _fresh(db, statement_id)).status is BankStatementStatus.PARSED


async def _candidate_for_auto_approve(db, user):
    """A statement that the parse marked as an auto-approve candidate: APPROVED, balanced, high confidence."""
    statement_id = await _approvable_statement(db, user)
    statement = await _fresh(db, statement_id)
    statement.status = BankStatementStatus.APPROVED
    statement.balance_validated = True
    statement.confidence_score = 95
    await db.commit()
    return statement_id


async def test_AC_extraction_2994_87_the_auto_approve_after_finish_run_still_posts(db, test_user):
    """AC-extraction.2994.87: finish_run comes first in the transaction, so the run is no longer active: it posts."""
    statement_id = await _candidate_for_auto_approve(db, test_user)
    run_id = await _running_run(db, statement_id, test_user)
    await finish_run(db, run_id)  # The worker does this before its auto-approve, in the same transaction.

    created = await try_auto_approve_high_confidence_statement(
        db, statement_id, test_user.id, dependencies=compose_statement_posting_dependencies()
    )
    await db.commit()

    assert created == len(ROWS)
    assert await _entry_count(db, test_user) >= len(ROWS)
    assert (await _fresh(db, statement_id)).status is BankStatementStatus.APPROVED


async def test_AC_extraction_2994_87_the_auto_approve_of_a_still_running_run_posts_nothing(db, test_user):
    """AC-extraction.2994.87: The order matters: against a running run the approve refuses, and nothing is posted."""
    statement_id = await _candidate_for_auto_approve(db, test_user)
    run_id = await _running_run(db, statement_id, test_user)
    user_id = test_user.id

    with pytest.raises(ActiveRunExists) as caught:
        await try_auto_approve_high_confidence_statement(
            db, statement_id, user_id, dependencies=compose_statement_posting_dependencies()
        )
    await db.rollback()

    assert caught.value.active_run_id == run_id
    assert await db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == user_id)) == 0
