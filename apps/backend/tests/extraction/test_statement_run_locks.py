"""Row locks and error text around the statement runs (#2994, slice S2 review).

The lock that a rerun takes on the statement row must let a run insert pass: a run insert takes a key share
of the statement row for its foreign key. A lock that blocks the key share lets the route and the worker
wait for each other, and Postgres then aborts one of them.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from src.composition import compose_statement_ingestion_use_case
from src.database import create_app_engine, create_session_maker_from_db
from src.extraction.extension import statement_parsing
from src.runtime import StorageError
from src.extraction import (
    ActiveRunExists,
    ParseJob,
    RetryableStatementIngestionError,
    BankStatementStatus,
    RunActorKind,
    RunHints,
    RunKind,
    RunTrigger,
    claim_run,
    create_run,
    fail_run,
    HintsNotApplicable,
    StatementStatusChanged,
    lock_statement_for_run,
    start_user_extract_run,
)
from tests.factories import StatementSummaryFactory

PARSING_ONLY = frozenset({BankStatementStatus.PARSING})


async def _parsing_statement_with_running_run(db, user):
    statement = StatementSummaryFactory.build(
        id=uuid4(), user_id=user.id, account_id=None, file_hash=f"locks-{uuid4()}", status=BankStatementStatus.PARSING
    )
    db.add(statement)
    await db.flush()
    run = await create_run(
        db,
        statement_id=statement.id,
        user_id=user.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.USER,
        trigger=RunTrigger.UPLOAD,
        hints=RunHints(keywords=["interest"], note="Credits."),
    )
    await claim_run(db, run.id)
    await db.commit()
    return statement.id, run.id


async def test_AC_extraction_2994_76_the_rerun_lock_lets_the_retry_run_insert_of_the_worker_pass(db, test_user):
    """AC-extraction.2994.76: The worker inserts its retry run while the route holds the statement lock: no deadlock."""
    statement_id, run_id = await _parsing_statement_with_running_run(db, test_user)
    maker = create_session_maker_from_db(db)

    async with maker() as route, maker() as worker:
        await route.execute(text("SET LOCAL lock_timeout = '1500ms'"))
        locked = await lock_statement_for_run(route, statement_id, test_user.id, allowed=PARSING_ONLY)
        assert locked is not None
        # The worker fails the old run and inserts the retry run, as `_end_failed_attempt` does.
        await worker.execute(text("SET LOCAL lock_timeout = '1500ms'"))
        failed = await fail_run(worker, run_id, error_code="retryable_error", error_message="The load failed.")
        successor = await create_run(
            worker,
            statement_id=statement_id,
            user_id=test_user.id,
            kind=RunKind.EXTRACT,
            actor_kind=RunActorKind.SYSTEM,
            trigger=RunTrigger.AUTO_RETRY,
            hints=RunHints(),
            parent_run_id=failed.id,
        )
        # The route then inserts its own run. It waits for the active retry run of the worker, and it ends with
        # a 409 once the worker commits. Neither session waits for the other in a circle.
        route_insert = asyncio.ensure_future(
            create_run(
                route,
                statement_id=statement_id,
                user_id=test_user.id,
                kind=RunKind.EXTRACT,
                actor_kind=RunActorKind.USER,
                trigger=RunTrigger.RERUN,
                hints=RunHints(),
            )
        )
        finished, _pending = await asyncio.wait({route_insert}, timeout=0.5)
        assert not finished, "the route insert must wait for the active retry run"
        await worker.commit()
        with pytest.raises(ActiveRunExists) as caught:
            await route_insert
        await route.rollback()

    assert caught.value.active_run_id == successor.id


async def test_AC_extraction_2994_76_the_rerun_lock_excludes_another_writer_but_not_a_key_share(db, test_user):
    """AC-extraction.2994.76: The lock is FOR NO KEY UPDATE: a second rerun waits, a foreign key check does not."""
    statement_id, _run_id = await _parsing_statement_with_running_run(db, test_user)
    maker = create_session_maker_from_db(db)
    sql = "SELECT id FROM statement_summaries WHERE id = :id FOR {mode} NOWAIT"

    async with maker() as route, maker() as other:
        locked = await lock_statement_for_run(route, statement_id, test_user.id, allowed=PARSING_ONLY)
        assert locked is not None

        # A key share is what the foreign key check of a run insert takes: it must pass.
        await other.execute(text(sql.format(mode="KEY SHARE")), {"id": statement_id})
        await other.rollback()
        # Any other writer, such as a second rerun or an approval, must not pass.
        for mode in ("NO KEY UPDATE", "UPDATE"):
            with pytest.raises(DBAPIError, match="could not obtain lock"):
                await other.execute(text(sql.format(mode=mode)), {"id": statement_id})
            await other.rollback()
        await route.rollback()


async def test_AC_extraction_2994_77_an_engine_error_text_holds_no_sql_parameter(test_database_url):
    """AC-extraction.2994.77: The engine of the app hides SQL parameters, so an error text never holds a hint."""
    secret = "DISTINCT-HINT-TEXT-77"
    statement = text("SELEKT :hints")  # A syntax error: the server error does not echo the parameter.

    plain = create_async_engine(test_database_url)
    guarded = create_app_engine(test_database_url)
    try:
        async with plain.connect() as connection:
            with pytest.raises(DBAPIError) as plain_error:
                await connection.execute(statement, {"hints": secret})
        async with guarded.connect() as connection:
            with pytest.raises(DBAPIError) as guarded_error:
                await connection.execute(statement, {"hints": secret})
    finally:
        await plain.dispose()
        await guarded.dispose()

    assert secret in str(plain_error.value), "the control engine must show that a default engine leaks the parameter"
    assert secret not in str(guarded_error.value)
    assert secret not in repr(guarded_error.value)


class _Loader:
    """A content loader that records how often the storage read runs."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> bytes:
        self.calls += 1
        return b"content"


async def _start(db, user, statement_id, loader, **overrides):
    arguments = {
        "statement_id": statement_id,
        "user_id": user.id,
        "file_type": "pdf",
        "hints": RunHints(keywords=["interest"]),
        "model": None,
        "allowed_statuses": frozenset({BankStatementStatus.PARSED}),
        "strict_hints": True,
        "load_content": loader,
    }
    return await start_user_extract_run(db, **{**arguments, **overrides})


async def _parsed_statement(db, user):
    statement = StatementSummaryFactory.build(
        id=uuid4(), user_id=user.id, account_id=None, file_hash=f"start-{uuid4()}", status=BankStatementStatus.PARSED
    )
    db.add(statement)
    await db.commit()
    return statement.id


async def test_AC_extraction_2994_79_start_user_extract_run_checks_the_csv_rule_before_it_reads_the_storage(db, test_user):
    """AC-extraction.2994.79: Hints on a CSV statement raise before the storage read, the lock and the run insert."""
    statement_id = await _parsed_statement(db, test_user)
    loader = _Loader()

    with pytest.raises(HintsNotApplicable):
        await _start(db, test_user, statement_id, loader, file_type="csv")

    assert loader.calls == 0
    kept = await _start(db, test_user, statement_id, loader, file_type="csv", strict_hints=False)
    assert kept.content == b"content" and loader.calls == 1
    await db.commit()
    from tests.extraction.test_statement_run_wiring import _runs

    (run,) = await _runs(db, statement_id)
    assert run.hints == {"keywords": [], "note": None}, "a CSV run keeps empty hints"


async def test_AC_extraction_2994_79_start_user_extract_run_sets_parsing_and_links_the_parent(db, test_user):
    """AC-extraction.2994.79: The function inserts the run with the latest run as parent, sets PARSING and clears the error."""
    from tests.extraction.test_statement_run_wiring import _runs, _statement

    statement_id = await _parsed_statement(db, test_user)
    first = await _start(db, test_user, statement_id, _Loader())
    first.statement.validation_error = "old error"
    await db.commit()
    await fail_run(db, first.run_id, error_code="done", error_message="Ended for the test.")
    first.statement.status = BankStatementStatus.REJECTED
    await db.commit()

    second = await _start(
        db, test_user, statement_id, _Loader(), allowed_statuses=frozenset({BankStatementStatus.REJECTED})
    )
    await db.commit()

    runs = await _runs(db, statement_id)
    statement = await _statement(db, statement_id)
    assert [run.seq for run in runs] == [1, 2]
    assert runs[1].id == second.run_id and runs[1].parent_run_id == first.run_id
    assert (runs[1].actor_kind, runs[1].trigger) == (RunActorKind.USER, RunTrigger.RERUN)
    assert statement.status is BankStatementStatus.PARSING and statement.validation_error is None


async def test_AC_extraction_2994_79_start_user_extract_run_writes_nothing_when_the_status_changed(db, test_user):
    """AC-extraction.2994.79: A status outside the allowed set raises StatementStatusChanged and inserts no run."""
    from tests.extraction.test_statement_run_wiring import _runs

    statement_id = await _parsed_statement(db, test_user)

    with pytest.raises(StatementStatusChanged):
        await _start(db, test_user, statement_id, _Loader(), allowed_statuses=frozenset({BankStatementStatus.REJECTED}))
    await db.rollback()

    assert await _runs(db, statement_id) == []


async def test_AC_extraction_2994_79_a_storage_failure_leaves_the_statement_and_the_runs_unchanged(db, test_user):
    """AC-extraction.2994.79: The storage read comes before the first write, so its failure writes nothing."""
    from tests.extraction.test_statement_run_wiring import _runs, _statement

    statement_id = await _parsed_statement(db, test_user)

    async def failing_loader() -> bytes:
        raise StorageError("the stored file is missing")

    with pytest.raises(StorageError):
        await _start(db, test_user, statement_id, failing_loader)
    await db.rollback()

    assert await _runs(db, statement_id) == []
    assert (await _statement(db, statement_id)).status is BankStatementStatus.PARSED


async def test_AC_extraction_2994_79_start_user_extract_run_takes_the_statement_lock_before_the_run_insert(db, test_user):
    """AC-extraction.2994.79: While the rerun waits for the lock, it has inserted no run, so another run insert passes."""
    statement_id = await _parsed_statement(db, test_user)
    maker = create_session_maker_from_db(db)

    async with maker() as blocker, maker() as route, maker() as other:
        # Another writer holds the statement row (FOR NO KEY UPDATE, so a run insert still passes the key check).
        # The rerun must wait here, before it writes a run.
        await blocker.execute(
            text("SELECT id FROM statement_summaries WHERE id = :id FOR NO KEY UPDATE"), {"id": statement_id}
        )
        rerun = asyncio.ensure_future(_start(route, test_user, statement_id, _Loader()))
        try:
            finished, _pending = await asyncio.wait({rerun}, timeout=0.5)
            assert not finished, "the rerun must wait for the row lock"

            # If the rerun had inserted its run first, this insert would wait for it in the unique index.
            await other.execute(text("SET LOCAL lock_timeout = '1500ms'"))
            competitor = await create_run(
                other,
                statement_id=statement_id,
                user_id=test_user.id,
                kind=RunKind.EXTRACT,
                actor_kind=RunActorKind.SYSTEM,
                trigger=RunTrigger.AUTO_RETRY,
                hints=RunHints(),
            )
            await other.commit()
            await blocker.rollback()
            with pytest.raises(ActiveRunExists) as caught:
                await rerun
            assert caught.value.active_run_id == competitor.id
        finally:
            if not rerun.done():
                await blocker.rollback()
                rerun.cancel()
                await asyncio.gather(rerun, return_exceptions=True)
            await route.rollback()


async def test_AC_extraction_2994_85_the_worker_retry_and_a_user_run_start_do_not_deadlock(db, test_user, monkeypatch):
    """AC-extraction.2994.85: The user start enters the run indexes while the worker retries: no deadlock, one winner."""
    statement_id, run_id = await _parsing_statement_with_running_run(db, test_user)
    maker = create_session_maker_from_db(db)
    use_case = compose_statement_ingestion_use_case(session_maker=maker)
    job = ParseJob(
        statement_id=statement_id,
        run_id=run_id,
        filename="retry.pdf",
        institution="DBS",
        user_id=test_user.id,
        account_id=None,
        file_hash="h" * 64,
        storage_key="statements/retry.pdf",
        model=None,
        request_id="req-retry",
    )
    old_run_failed = asyncio.Event()
    real_fail_run = statement_parsing.fail_run

    async def fail_then_let_the_user_start_in(*args, **kwargs):
        failed = await real_fail_run(*args, **kwargs)
        old_run_failed.set()
        # The user start now reaches its run insert, before the worker inserts its retry run.
        await asyncio.sleep(0.5)
        return failed

    monkeypatch.setattr(statement_parsing, "fail_run", fail_then_let_the_user_start_in)

    async def worker():
        return await use_case._end_failed_attempt(job, RetryableStatementIngestionError("load failed"), attempt=1)

    async def user_start():
        await old_run_failed.wait()
        async with maker() as route:
            try:
                return await _start(
                    route, test_user, statement_id, _Loader(), allowed_statuses=PARSING_ONLY, hints=RunHints()
                )
            finally:
                await route.rollback()

    retry_job, user_result = await asyncio.gather(worker(), user_start(), return_exceptions=True)

    assert isinstance(retry_job, ParseJob), f"the retry of the worker must succeed, not end in {retry_job!r}"
    assert isinstance(user_result, ActiveRunExists), f"the user start must end with a 409, not {user_result!r}"
    assert user_result.active_run_id == retry_job.run_id
