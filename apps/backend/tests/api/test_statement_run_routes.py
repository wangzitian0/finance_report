"""Upload, retry and reject create statement runs (#2994, slice S1 phase B).

The run row is created in the same transaction as the statement change and committed before the
dispatch. A second reparse while a run is active returns 409 with `active_run_id`.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from src.database import create_session_maker_from_db
from src.extraction import (
    BankStatementStatus,
    ParseJob,
    RunActorKind,
    RunHints,
    RunKind,
    RunState,
    RunTrigger,
    StatementSummary,
    create_run,
    fail_run,
)
from src.extraction.extension import statement_pipeline
from src.extraction.orm.statement_run import StatementRun
from src.routers import statements as statements_router
from src.schemas import RetryParsingRequest, StatementDecisionRequest
from tests.api._statement_router_fixtures import (
    _compose_mock_ingestion,
    build_statement,
    make_upload_file,
    seed_uploaded_document,
)


async def _statement_with_document(db, user, *, status, file_hash, validation_error=None) -> StatementSummary:
    statement = build_statement(user.id, file_hash, 70)
    statement.status = status
    statement.validation_error = validation_error
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path=f"statements/{file_hash}.pdf", original_filename="run.pdf")
    await db.commit()
    return statement


async def _runs(db, statement_id) -> list[StatementRun]:
    rows = await db.execute(
        select(StatementRun)
        .where(StatementRun.statement_id == statement_id)
        .order_by(StatementRun.seq)
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


def _capture_dispatch(monkeypatch) -> list[ParseJob]:
    jobs: list[ParseJob] = []

    async def capture(*, job, content):
        jobs.append(job)

    monkeypatch.setattr(statement_pipeline, "compose_statement_ingestion_use_case", _compose_mock_ingestion(capture))
    return jobs


async def test_AC_extraction_2994_16_upload_creates_the_extract_run_before_dispatch(
    db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    """AC-extraction.2994.16: Upload commits the statement and its extract run, then dispatches the job."""
    maker = create_session_maker_from_db(db)
    seen: dict[str, object] = {}

    async def execute(*, job, content):
        async with maker() as other_session:
            seen["run"] = await other_session.get(StatementRun, job.run_id)
            seen["statement"] = await other_session.get(StatementSummary, job.statement_id)
        seen["job"] = job

    monkeypatch.setattr(statement_pipeline, "compose_statement_ingestion_use_case", _compose_mock_ingestion(execute))
    upload = make_upload_file("june.pdf", b"upload-run-content")

    created = await statements_router.upload_statement(
        file=upload, institution="DBS", account_id=None, model=None, db=db, user_id=test_user.id
    )
    await upload.close()
    await statements_router.wait_for_parse_tasks()

    run = seen["run"]
    assert run is not None, "the dispatched job names a run that another session cannot read"
    assert seen["statement"] is not None
    assert run.statement_id == created.id
    assert run.user_id == test_user.id
    assert (run.seq, run.kind, run.state) == (1, RunKind.EXTRACT, RunState.REQUESTED)
    assert (run.actor_kind, run.trigger) == (RunActorKind.USER, RunTrigger.UPLOAD)
    assert run.hints == {"keywords": [], "note": None}
    assert run.parent_run_id is None
    assert seen["job"].statement_id == created.id


async def test_AC_extraction_2994_17_a_failed_run_insert_leaves_no_statement(
    db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    """AC-extraction.2994.17: The run insert and the statement insert commit together or not at all."""
    dispatched = _capture_dispatch(monkeypatch)

    async def broken_create_run(*_args, **_kwargs):
        raise RuntimeError("the run insert failed")

    monkeypatch.setattr(statements_router, "create_run", broken_create_run)
    upload = make_upload_file("july.pdf", b"upload-run-failure-content")
    user_id = test_user.id

    with pytest.raises(HTTPException) as caught:
        await statements_router.upload_statement(
            file=upload, institution="DBS", account_id=None, model=None, db=db, user_id=test_user.id
        )
    await upload.close()

    assert caught.value.status_code == 500
    assert dispatched == []
    assert await db.scalar(select(func.count()).select_from(StatementSummary).where(StatementSummary.user_id == user_id)) == 0
    assert await db.scalar(select(func.count()).select_from(StatementRun).where(StatementRun.user_id == user_id)) == 0


async def test_AC_extraction_2994_18_a_reparse_creates_a_rerun_with_the_previous_run_as_parent(
    db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    """AC-extraction.2994.18: A reparse writes a user rerun run, sets PARSING and clears the error."""
    statement = await _statement_with_document(
        db, test_user, status=BankStatementStatus.REJECTED, file_hash="hash_reparse_run", validation_error="old error"
    )
    statement_id = statement.id
    previous = await create_run(
        db,
        statement_id=statement_id,
        user_id=test_user.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.SYSTEM,
        trigger=RunTrigger.UPLOAD,
        hints=RunHints(),
    )
    await fail_run(db, previous.id, error_code="extraction_error", error_message="The parse failed.")
    await db.commit()
    previous_id = previous.id
    jobs = _capture_dispatch(monkeypatch)

    response = await statements_router.retry_statement_parsing(
        statement_id, RetryParsingRequest(model=None), db=db, user_id=test_user.id
    )
    await statements_router.wait_for_parse_tasks()

    runs = await _runs(db, statement_id)
    assert [run.seq for run in runs] == [1, 2]
    assert (runs[1].kind, runs[1].state) == (RunKind.EXTRACT, RunState.REQUESTED)
    assert (runs[1].actor_kind, runs[1].trigger) == (RunActorKind.USER, RunTrigger.RERUN)
    assert runs[1].parent_run_id == previous_id
    assert response.status == BankStatementStatus.PARSING
    assert response.validation_error is None
    assert [job.run_id for job in jobs] == [runs[1].id]


async def test_AC_extraction_2994_19_a_reparse_while_a_run_is_active_returns_409_with_the_active_run_id(
    client, db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    """AC-extraction.2994.19: The retry route and the reject route return 409 and start no second run."""
    jobs = _capture_dispatch(monkeypatch)
    retry_statement = await _statement_with_document(
        db, test_user, status=BankStatementStatus.PARSING, file_hash="hash_active_retry"
    )
    retry_statement_id = retry_statement.id
    active = await create_run(
        db,
        statement_id=retry_statement_id,
        user_id=test_user.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.SYSTEM,
        trigger=RunTrigger.UPLOAD,
        hints=RunHints(),
    )
    await db.commit()
    active_id = active.id

    retried = await client.post(f"/statements/{retry_statement_id}/retry", json={})

    assert retried.status_code == 409, retried.text
    assert retried.json()["active_run_id"] == str(active_id)
    assert retried.json()["error_id"] == "conflict"
    assert [run.id for run in await _runs(db, retry_statement_id)] == [active_id]

    reject_statement = await _statement_with_document(
        db, test_user, status=BankStatementStatus.PARSED, file_hash="hash_active_reject"
    )
    reject_statement_id = reject_statement.id
    other_active = await create_run(
        db,
        statement_id=reject_statement_id,
        user_id=test_user.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.SYSTEM,
        trigger=RunTrigger.UPLOAD,
        hints=RunHints(),
    )
    await db.commit()
    other_active_id = other_active.id

    rejected = await client.post(f"/statements/{reject_statement_id}/review/reject", json={"notes": "check again"})

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["active_run_id"] == str(other_active_id)
    assert [run.id for run in await _runs(db, reject_statement_id)] == [other_active_id]
    assert jobs == []
    untouched = await db.scalar(
        select(StatementSummary)
        .where(StatementSummary.id == reject_statement_id)
        .execution_options(populate_existing=True)
    )
    assert untouched.status is BankStatementStatus.PARSED, "a 409 must come before any write of the reject"
    assert untouched.stage1_reviewed_at is None


async def test_AC_extraction_2994_20_reject_then_reparse_shows_parsing_while_the_job_runs(
    db, monkeypatch, storage_stub, test_user
):
    """AC-extraction.2994.20: A reject followed by its reparse leaves PARSING, not REJECTED, with a new run."""
    statement = await _statement_with_document(
        db, test_user, status=BankStatementStatus.PARSED, file_hash="hash_reject_then_reparse"
    )
    statement_id = statement.id
    jobs = _capture_dispatch(monkeypatch)

    response = await statements_router.reject_statement_stage1(
        statement_id=statement_id,
        decision=StatementDecisionRequest(notes="Needs re-parse"),
        db=db,
        user_id=test_user.id,
    )
    await statements_router.wait_for_parse_tasks()

    runs = await _runs(db, statement_id)
    assert response.status == BankStatementStatus.PARSING
    assert response.validation_error is None
    assert [(run.trigger, run.actor_kind, run.state) for run in runs] == [
        (RunTrigger.RERUN, RunActorKind.USER, RunState.REQUESTED)
    ]
    assert [job.run_id for job in jobs] == [runs[0].id]


def test_AC_extraction_2994_21_the_retry_flag_and_the_watchdog_are_gone():
    """AC-extraction.2994.21: The reparse has no reset_for_retry parameter and the watchdog no longer exists."""
    import inspect

    from src.extraction.extension import statement_parsing_supervisor as supervisor

    assert "reset_for_retry" not in inspect.signature(statements_router._queue_statement_reparse).parameters
    assert not hasattr(supervisor, "reset_stale_parsing_jobs")
    assert not hasattr(supervisor, "PARSING_STALE_THRESHOLD")


async def test_AC_extraction_2994_39_two_concurrent_rejects_give_one_200_and_one_409(
    client, db, monkeypatch, storage_stub, test_user
):
    """AC-extraction.2994.39: The run insert decides the race: the statement is never REJECTED while a run is active."""
    jobs = _capture_dispatch(monkeypatch)

    for round_number in range(6):
        statement = await _statement_with_document(
            db, test_user, status=BankStatementStatus.PARSED, file_hash=f"hash_double_reject_{round_number}"
        )
        statement_id = statement.id
        first, second = await asyncio.gather(
            client.post(f"/statements/{statement_id}/review/reject", json={"notes": "double click"}),
            client.post(f"/statements/{statement_id}/review/reject", json={"notes": "double click"}),
        )

        assert sorted([first.status_code, second.status_code]) == [200, 409], (first.text, second.text)
        loser = first if first.status_code == 409 else second
        runs = await _runs(db, statement_id)
        assert len(runs) == 1
        assert loser.json()["active_run_id"] == str(runs[0].id)
        final = await db.scalar(
            select(StatementSummary)
            .where(StatementSummary.id == statement_id)
            .execution_options(populate_existing=True)
        )
        assert final.status is BankStatementStatus.PARSING
    await statements_router.wait_for_parse_tasks()
    assert len(jobs) == 6


async def test_AC_extraction_2994_40_the_reject_notes_become_the_hint_note_of_the_rerun(
    client, db, monkeypatch, storage_stub, test_user
):
    """AC-extraction.2994.40: The notes of a reject reach the run row; more than 500 characters give 422."""
    jobs = _capture_dispatch(monkeypatch)
    too_long = await _statement_with_document(
        db, test_user, status=BankStatementStatus.PARSED, file_hash="hash_notes_too_long"
    )
    too_long_id = too_long.id
    rejected_long = await client.post(f"/statements/{too_long_id}/review/reject", json={"notes": "n" * 501})
    rejected_control = await client.post(f"/statements/{too_long_id}/review/reject", json={"notes": "bell\x07"})
    assert rejected_long.status_code == 422, rejected_long.text
    assert rejected_long.json()["detail"][0]["type"] == "string_too_long", "the schema holds the limit"
    assert rejected_control.status_code == 422, rejected_control.text
    assert await _runs(db, too_long_id) == []
    untouched = await db.scalar(
        select(StatementSummary).where(StatementSummary.id == too_long_id).execution_options(populate_existing=True)
    )
    assert untouched.status is BankStatementStatus.PARSED

    exact = await _statement_with_document(db, test_user, status=BankStatementStatus.PARSED, file_hash="hash_notes_ok")
    exact_id = exact.id
    accepted = await client.post(f"/statements/{exact_id}/review/reject", json={"notes": "n" * 500})
    plain = await _statement_with_document(db, test_user, status=BankStatementStatus.PARSED, file_hash="hash_notes_none")
    plain_id = plain.id
    without_notes = await client.post(f"/statements/{plain_id}/review/reject", json={})
    await statements_router.wait_for_parse_tasks()

    assert accepted.status_code == 200, accepted.text
    assert without_notes.status_code == 200, without_notes.text
    (exact_run,) = await _runs(db, exact_id)
    (plain_run,) = await _runs(db, plain_id)
    assert exact_run.hints == {"keywords": [], "note": "n" * 500}
    assert plain_run.hints == {"keywords": [], "note": None}
    assert len(jobs) == 2


async def test_AC_extraction_2994_42_a_retryable_failure_through_the_router_waits_for_the_retry_delay(
    db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    """AC-extraction.2994.42: With the default delay the retry is still pending after 1.5 s, and a cancel leaks no task."""
    from src.extraction.extension import statement_parsing

    async def provider_down(self, *_args, **_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(statement_parsing.ExtractionService, "parse_document", provider_down)
    assert statement_parsing.PARSE_RETRY_DELAY_SECONDS == 30
    upload = make_upload_file("slow-retry.pdf", b"retry-delay-content")

    created = await statements_router.upload_statement(
        file=upload, institution="DBS", account_id=None, model=None, db=db, user_id=test_user.id
    )
    await upload.close()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(statements_router.wait_for_parse_tasks(), timeout=1.5)
    await asyncio.sleep(0.1)

    runs = await _runs(db, created.id)
    assert [(run.seq, run.state, run.trigger) for run in runs] == [
        (1, RunState.FAILED, RunTrigger.UPLOAD),
        (2, RunState.REQUESTED, RunTrigger.AUTO_RETRY),
    ]
    assert statements_router._PENDING_PARSE_TASKS == set(), "the cancelled wait must leave no task behind"
