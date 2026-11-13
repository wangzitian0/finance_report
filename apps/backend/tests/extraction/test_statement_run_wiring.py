"""The parse job, the worker, the retry loop and the supervisor use statement runs (#2994, slice S1 phase B).

The worker claims the run first, beats the heartbeat on the run row, and finishes or fails the run in the
same transaction as its final commit. A retryable failure chains system runs. The supervisor fails stale
runs and rejects the statements that they leave in PARSING.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from src.composition import compose_statement_ingestion_use_case
from src.database import create_session_maker_from_db
from src.extraction import (
    BankStatementStatus,
    ExtractionError,
    ParseJob,
    RetryableStatementIngestionError,
    RunActorKind,
    RunHints,
    RunKind,
    RunState,
    RunTrigger,
    StatementIngestionStatus,
    StatementSummary,
    claim_run,
    create_run,
    fail_run,
    reap_stale_runs,
)
from src.audit.orm import TraceRecordRow
from src.extraction.extension import statement_parsing_supervisor as supervisor
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_parsing import handle_parse_failure
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.extraction.orm.statement_run import StatementRun
from src.runtime import StorageError
from tests.factories import AccountFactory, StatementSummaryFactory

CSV = (
    b"Statement Currency,Date,Description,Debit Amount,Credit Amount\n"
    b"SGD,2026-01-05,Salary,,5000.00\n"
    b"SGD,2026-01-20,Rent,1500.00,\n"
)


class Sleeps:
    """Records the waits of the retry loop so a test does not wait."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


class ScriptedService:
    """Raise the scripted error of each call, then parse with the real service."""

    def __init__(self, errors: list[BaseException | None]) -> None:
        self.errors = list(errors)
        self.calls = 0
        self.real = ExtractionService()

    async def parse_document(self, *args, **kwargs):
        self.calls += 1
        error = self.errors.pop(0) if self.errors else None
        if error is not None:
            raise error
        return await self.real.parse_document(*args, **kwargs)


class ScriptedLoader:
    """Raise the scripted storage error of each call, then return the source bytes."""

    def __init__(self, errors: list[BaseException | None]) -> None:
        self.errors = list(errors)
        self.calls = 0

    async def __call__(self, _storage_key: str) -> bytes:
        self.calls += 1
        error = self.errors.pop(0) if self.errors else None
        if error is not None:
            raise error
        return CSV


class ForbiddenService:
    async def parse_document(self, *_args, **_kwargs):
        raise AssertionError("the worker called the model for a run that it could not claim")


def _use_case(db, service=None, sleeps: Sleeps | None = None, **overrides):
    use_case = compose_statement_ingestion_use_case(session_maker=create_session_maker_from_db(db))
    changes = {"sleep": sleeps or Sleeps(), **overrides}
    if service is not None:
        changes["extraction_service_factory"] = lambda: service
    return replace(use_case, **changes)


async def _statement_with_run(
    db, user, *, content: bytes = CSV, name: str = "wiring.csv", hints: RunHints | None = None, model: str | None = None
) -> tuple[UUID, ParseJob]:
    file_hash = hashlib.sha256(content).hexdigest()
    statement = StatementSummaryFactory.build(
        id=uuid4(),
        user_id=user.id,
        account_id=None,
        file_hash=file_hash,
        institution="DBS",
        status=BankStatementStatus.PARSING,
        confidence_score=None,
        balance_validated=None,
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
        hints=hints or RunHints(),
        model=model,
    )
    await db.commit()
    job = ParseJob(
        statement_id=statement.id,
        run_id=run.id,
        filename=name,
        institution="DBS",
        user_id=user.id,
        account_id=None,
        file_hash=file_hash,
        storage_key=f"statements/{name}",
        model=model,
        request_id=f"req-{name}",
    )
    return statement.id, job


async def _runs(db, statement_id: UUID) -> list[StatementRun]:
    rows = await db.execute(
        select(StatementRun)
        .where(StatementRun.statement_id == statement_id)
        .order_by(StatementRun.seq)
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


async def _statement(db, statement_id: UUID) -> StatementSummary:
    return await db.scalar(
        select(StatementSummary).where(StatementSummary.id == statement_id).execution_options(populate_existing=True)
    )


async def _count(db, model, *where) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*where))


def _prefect_params(**changes) -> dict[str, str | None]:
    params = {
        "statement_id": str(uuid4()),
        "run_id": str(uuid4()),
        "filename": "x.pdf",
        "institution": None,
        "user_id": str(uuid4()),
        "account_id": None,
        "file_hash": "h",
        "storage_key": "statements/x.pdf",
        "model": None,
        "request_id": None,
    }
    return {**params, **changes}


def test_AC_extraction_2994_15_the_parse_job_requires_a_run_id():
    """AC-extraction.2994.15: A job has a run id, the Prefect parameters carry it, and a job without it fails."""
    with pytest.raises(TypeError, match="run_id"):
        ParseJob(
            statement_id=uuid4(),
            filename="x.pdf",
            institution=None,
            user_id=uuid4(),
            account_id=None,
            file_hash="h",
            storage_key="k",
            model=None,
        )
    params = _prefect_params()
    job = ParseJob.from_prefect_params(params)
    assert job.run_id == UUID(params["run_id"])
    assert job.to_prefect_params()["run_id"] == params["run_id"]
    assert ParseJob.from_prefect_params(job.to_prefect_params()) == job
    without_run = {key: value for key, value in params.items() if key != "run_id"}
    with pytest.raises(ValueError, match="run_id"):
        ParseJob.from_prefect_params(without_run)


async def test_AC_extraction_2994_22_a_worker_does_not_parse_a_run_that_it_cannot_claim(db, test_user):
    """AC-extraction.2994.22: A claim that finds no requested run ends the job before any model call."""
    statement_id, job = await _statement_with_run(db, test_user)
    from src.extraction import claim_run

    await claim_run(db, job.run_id)
    await db.commit()

    outcome = await _use_case(db, ForbiddenService()).execute(job, content=CSV)

    assert outcome.status is StatementIngestionStatus.RUN_STALE
    assert (await _statement(db, statement_id)).status is BankStatementStatus.PARSING
    assert [run.state for run in await _runs(db, statement_id)] == [RunState.RUNNING]
    assert await _count(db, AtomicTransaction, AtomicTransaction.user_id == test_user.id) == 0


async def test_AC_extraction_2994_23_a_successful_parse_finishes_its_run_with_the_result_id(db, test_user):
    """AC-extraction.2994.23: The run ends succeeded with the id of the stored extraction result."""
    statement_id, job = await _statement_with_run(db, test_user)

    outcome = await _use_case(db).execute(job, content=CSV)

    statement = await _statement(db, statement_id)
    (run,) = await _runs(db, statement_id)
    assert outcome.status is StatementIngestionStatus.COMPLETED
    assert statement.status is BankStatementStatus.PARSED
    assert statement.current_extraction_result_id is not None
    assert run.state is RunState.SUCCEEDED
    assert run.extraction_result_id == statement.current_extraction_result_id
    assert run.started_at is not None
    assert run.finished_at is not None
    stored = await db.get(StatementExtractionResultRecord, run.extraction_result_id)
    assert stored.statement_id == statement_id
    records = await db.execute(
        select(TraceRecordRow.assertion_id)
        .where(TraceRecordRow.execution_id == f"statement:{statement_id}:run:{run.id}")
        .order_by(TraceRecordRow.occurred_at)
    )
    assert list(records.scalars()) == ["extract.requested", "extract.running", "extract.succeeded"]


async def test_AC_extraction_2994_24_the_run_finishes_in_the_transaction_of_the_final_commit(db, test_user):
    """AC-extraction.2994.24: A failure before the final commit leaves no succeeded run and no stored result."""
    statement_id, job = await _statement_with_run(db, test_user)
    router_calls = 0

    async def failing_router_once(**_kwargs) -> None:
        nonlocal router_calls
        router_calls += 1
        if router_calls == 1:
            raise RuntimeError("the router failed after finish_run")

    outcome = await _use_case(db, brokerage_router=failing_router_once).execute(job, content=CSV)

    first, second = await _runs(db, statement_id)
    assert outcome.status is StatementIngestionStatus.COMPLETED
    assert (first.state, second.state) == (RunState.FAILED, RunState.SUCCEEDED)
    assert first.extraction_result_id is None
    first_records = await db.execute(
        select(TraceRecordRow.assertion_id).where(
            TraceRecordRow.execution_id == f"statement:{statement_id}:run:{first.id}"
        )
    )
    assert "extract.succeeded" not in set(first_records.scalars())
    assert await _count(db, StatementExtractionResultRecord, StatementExtractionResultRecord.statement_id == statement_id) == 1


async def test_AC_extraction_2994_25_a_finish_after_the_reaper_failed_the_run_discards_the_parse(db, test_user):
    """AC-extraction.2994.25: A parse that ends after the reaper failed its run changes nothing (#2960)."""
    statement_id, job = await _statement_with_run(db, test_user)
    sessions = create_session_maker_from_db(db)

    class ReapedDuringParse(ScriptedService):
        async def parse_document(self, *args, **kwargs):
            async with sessions() as other_session:
                assert await reap_stale_runs(other_session, now=datetime.now(UTC) + timedelta(minutes=10))
                await other_session.commit()
            return await super().parse_document(*args, **kwargs)

    outcome = await _use_case(db, ReapedDuringParse([])).execute(job, content=CSV)

    statement = await _statement(db, statement_id)
    (run,) = await _runs(db, statement_id)
    assert outcome.status is StatementIngestionStatus.RUN_STALE
    assert run.state is RunState.FAILED
    assert run.error_code == "heartbeat_lost"
    assert run.extraction_result_id is None
    assert statement.status is BankStatementStatus.PARSING
    assert statement.current_extraction_result_id is None
    assert await _count(db, AtomicTransaction, AtomicTransaction.user_id == test_user.id) == 0
    assert await _count(db, StatementExtractionResultRecord, StatementExtractionResultRecord.statement_id == statement_id) == 0


async def test_AC_extraction_2994_26_an_extraction_error_fails_the_run_and_rejects_the_statement(db, test_user):
    """AC-extraction.2994.26: A source rejection fails the run with a code and a redacted message, with no retry."""
    statement_id, job = await _statement_with_run(db, test_user)
    long_message = "Cannot read the file of owner@example.com. " + "x" * 900
    sleeps = Sleeps()

    outcome = await _use_case(db, ScriptedService([ExtractionError(long_message)]), sleeps).execute(job, content=CSV)

    statement = await _statement(db, statement_id)
    (run,) = await _runs(db, statement_id)
    assert outcome.status is StatementIngestionStatus.SOURCE_REJECTED
    assert statement.status is BankStatementStatus.REJECTED
    assert run.state is RunState.FAILED
    assert run.error_code == "extraction_error"
    assert run.error_message is not None
    assert len(run.error_message) <= 500
    assert "owner@example.com" not in run.error_message
    assert sleeps.delays == []


async def test_AC_extraction_2994_27_a_late_failure_does_not_touch_a_statement_that_a_new_run_owns(db, test_user):
    """AC-extraction.2994.27: A failure report of a reaped run leaves the status of the statement alone."""
    statement_id, job = await _statement_with_run(db, test_user)
    from src.extraction import claim_run

    await claim_run(db, job.run_id)
    await db.commit()
    assert await reap_stale_runs(db, now=datetime.now(UTC) + timedelta(minutes=10)) == [job.run_id]
    await create_run(
        db,
        statement_id=statement_id,
        user_id=test_user.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.USER,
        trigger=RunTrigger.RERUN,
        hints=RunHints(),
    )
    await db.commit()
    statement = await _statement(db, statement_id)

    await handle_parse_failure(
        statement, db, job=job, message="late failure", error_type="ExtractionError", phase="extraction_started"
    )

    assert (await _statement(db, statement_id)).status is BankStatementStatus.PARSING
    first, second = await _runs(db, statement_id)
    assert (first.state, first.error_code) == (RunState.FAILED, "heartbeat_lost")
    assert second.state is RunState.REQUESTED


async def test_AC_extraction_2994_28_a_retryable_error_chains_system_runs_up_to_three_attempts(db, test_user):
    """AC-extraction.2994.28: Two content-load failures give three linked runs, and the third run succeeds."""
    statement_id, job = await _statement_with_run(db, test_user)
    sleeps = Sleeps()
    loader = ScriptedLoader([StorageError("storage down 1"), StorageError("storage down 2"), None])

    outcome = await _use_case(db, sleeps=sleeps, content_loader=loader).execute(job)

    first, second, third = await _runs(db, statement_id)
    assert outcome.status is StatementIngestionStatus.COMPLETED
    assert loader.calls == 3
    assert sleeps.delays == [30, 30]
    assert [run.seq for run in (first, second, third)] == [1, 2, 3]
    assert [run.state for run in (first, second, third)] == [RunState.FAILED, RunState.FAILED, RunState.SUCCEEDED]
    assert [run.parent_run_id for run in (first, second, third)] == [None, first.id, second.id]
    assert [run.actor_kind for run in (first, second, third)] == [
        RunActorKind.USER,
        RunActorKind.SYSTEM,
        RunActorKind.SYSTEM,
    ]
    assert [run.trigger for run in (first, second, third)] == [
        RunTrigger.UPLOAD,
        RunTrigger.AUTO_RETRY,
        RunTrigger.AUTO_RETRY,
    ]
    assert first.error_code == "retryable_statement_ingestion_error"
    assert "Statement content load failed: storage down 1" in first.error_message
    assert (await _statement(db, statement_id)).status is BankStatementStatus.PARSED


async def test_AC_extraction_2994_29_three_failed_attempts_leave_the_statement_to_the_supervisor(db, test_user):
    """AC-extraction.2994.29: After the third failed attempt the error reaches the caller; the supervisor rejects it."""
    statement_id, job = await _statement_with_run(db, test_user)
    sleeps = Sleeps()
    loader = ScriptedLoader([StorageError("down 1"), StorageError("down 2"), StorageError("down 3"), None])

    with pytest.raises(RetryableStatementIngestionError):
        await _use_case(db, sleeps=sleeps, content_loader=loader).execute(job)

    runs = await _runs(db, statement_id)
    statement = await _statement(db, statement_id)
    assert loader.calls == 3
    assert sleeps.delays == [30, 30]
    assert [run.state for run in runs] == [RunState.FAILED] * 3
    assert "down 3" in (runs[2].error_message or "")
    assert await _count(db, StatementRun, StatementRun.state.in_([RunState.REQUESTED, RunState.RUNNING])) == 0
    assert statement.status is BankStatementStatus.PARSING, "an application error alone does not reject the source"

    assert await supervisor.reap_stale_parsing_runs(create_session_maker_from_db(db)) == 1

    rejected = await _statement(db, statement_id)
    assert rejected.status is BankStatementStatus.REJECTED
    assert rejected.validation_error == "Parsing failed. Please retry."


async def test_AC_extraction_2994_34_a_worker_claims_the_run_before_it_loads_the_content(db, test_user):
    """AC-extraction.2994.34: A second worker for a claimed run loads nothing and cannot fail the run."""
    statement_id, job = await _statement_with_run(db, test_user)
    await claim_run(db, job.run_id)
    await db.commit()
    loader = ScriptedLoader([StorageError("storage down")])

    outcome = await _use_case(db, ForbiddenService(), content_loader=loader).execute(job)

    (run,) = await _runs(db, statement_id)
    assert outcome.status is StatementIngestionStatus.RUN_STALE
    assert loader.calls == 0
    assert (run.state, run.error_code) == (RunState.RUNNING, None)


async def test_AC_extraction_2994_35_a_worker_stops_when_the_heartbeat_finds_its_run_gone(db, test_user, monkeypatch):
    """AC-extraction.2994.35: A heartbeat that finds the run no longer running cancels the parse and writes nothing."""
    statement_id, job = await _statement_with_run(db, test_user)
    monkeypatch.setattr(supervisor, "PARSING_HEARTBEAT_INTERVAL_SECONDS", 0.05)

    async def run_is_gone(_session, _run_id) -> bool:
        return False

    monkeypatch.setattr(supervisor, "heartbeat_run", run_is_gone)
    cancelled = asyncio.Event()

    class SlowService:
        async def parse_document(self, *_args, **_kwargs):
            try:
                await asyncio.sleep(6)
            except asyncio.CancelledError:
                cancelled.set()
                raise

    outcome = await asyncio.wait_for(_use_case(db, SlowService()).execute(job, content=CSV), timeout=3)

    (run,) = await _runs(db, statement_id)
    assert outcome.status is StatementIngestionStatus.RUN_STALE
    assert cancelled.is_set()
    assert (run.state, run.error_code) == (RunState.RUNNING, None), "the cancelled worker writes nothing"
    assert (await _statement(db, statement_id)).status is BankStatementStatus.PARSING


async def test_AC_extraction_2994_38_an_error_inside_parse_document_is_not_retried(db, test_user, monkeypatch):
    """AC-extraction.2994.38: The service wraps every error in ExtractionError, which rejects the source without a retry."""
    statement_id, job = await _statement_with_run(db, test_user)

    async def lost_database(*_args, **_kwargs):
        raise RuntimeError("database connection lost")

    monkeypatch.setattr("src.extraction.extension.service.dual_write_layer2", lost_database)
    sleeps = Sleeps()

    outcome = await _use_case(db, sleeps=sleeps).execute(job, content=CSV)

    (run,) = await _runs(db, statement_id)
    assert outcome.status is StatementIngestionStatus.SOURCE_REJECTED
    assert run.state is RunState.FAILED
    assert run.error_code == "extraction_error"
    assert "database connection lost" in run.error_message
    assert (await _statement(db, statement_id)).status is BankStatementStatus.REJECTED
    assert sleeps.delays == []


def test_AC_extraction_2994_30_the_prefect_flow_has_no_retries():
    """AC-extraction.2994.30: Only the use case retries, so the flow definition holds no retries."""
    from src.extraction.extension.statement_flow import parse_statement_flow

    assert not parse_statement_flow.retries


async def _run_of_statement(db, user, *, status, kind=RunKind.EXTRACT, file_hash) -> tuple[UUID, UUID]:
    account = await AccountFactory.create_async(db, user_id=user.id, name=f"Supervisor bank {file_hash}")
    statement = StatementSummaryFactory.build(
        id=uuid4(),
        user_id=user.id,
        account_id=account.id,
        file_hash=file_hash,
        institution="DBS",
        status=status,
        currency="SGD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("110.00"),
    )
    db.add(statement)
    await db.flush()
    run = await create_run(
        db,
        statement_id=statement.id,
        user_id=user.id,
        kind=kind,
        actor_kind=RunActorKind.SYSTEM,
        trigger=RunTrigger.UPLOAD,
        hints=RunHints(),
    )
    await db.commit()
    from src.extraction import claim_run

    await claim_run(db, run.id)
    await db.commit()
    return statement.id, run.id


async def test_AC_extraction_2994_31_the_supervisor_rejects_a_parsing_statement_that_has_no_active_run(db, test_user):
    """AC-extraction.2994.31: A reaped extract run or a last failed attempt rejects its PARSING statement."""
    parsing, parsing_run = await _run_of_statement(db, test_user, status=BankStatementStatus.PARSING, file_hash="sup-1")
    parsed, parsed_run = await _run_of_statement(db, test_user, status=BankStatementStatus.PARSED, file_hash="sup-2")
    approved, approved_run = await _run_of_statement(db, test_user, status=BankStatementStatus.APPROVED, file_hash="sup-3")
    classify, classify_run = await _run_of_statement(
        db, test_user, status=BankStatementStatus.PARSED, kind=RunKind.CLASSIFY, file_hash="sup-4"
    )
    fresh, fresh_run = await _run_of_statement(db, test_user, status=BankStatementStatus.PARSING, file_hash="sup-5")
    orphan, orphan_run = await _run_of_statement(db, test_user, status=BankStatementStatus.PARSING, file_hash="sup-6")
    old = datetime.now(UTC) - timedelta(minutes=10)
    from sqlalchemy import update

    await fail_run(db, orphan_run, error_code="retryable_statement_ingestion_error", error_message="Failed.")
    await db.execute(
        update(StatementRun)
        .where(StatementRun.id.in_([parsing_run, parsed_run, approved_run, classify_run]))
        .values(heartbeat_at=old)
    )
    await db.commit()

    count = await supervisor.reap_stale_parsing_runs(create_session_maker_from_db(db))

    assert count == 5
    for rejected_id, message in (
        (parsing, "Parsing timed out. Please retry."),
        (orphan, "Parsing failed. Please retry."),
    ):
        rejected = await _statement(db, rejected_id)
        assert rejected.status is BankStatementStatus.REJECTED
        assert rejected.validation_error == message
        assert rejected.confidence_score == 0
        assert rejected.balance_validated is False
    assert (await _statement(db, parsed)).status is BankStatementStatus.PARSED
    assert (await _statement(db, approved)).status is BankStatementStatus.APPROVED
    assert (await _statement(db, classify)).status is BankStatementStatus.PARSED
    assert (await _statement(db, fresh)).status is BankStatementStatus.PARSING
    assert (await _runs(db, parsing))[0].error_code == "heartbeat_lost"
    assert (await _runs(db, fresh))[0].state is RunState.RUNNING
    assert await supervisor.reap_stale_parsing_runs(create_session_maker_from_db(db)) == 0


async def test_AC_extraction_2994_36_the_supervisor_skips_a_statement_that_another_transaction_holds(db, test_user):
    """AC-extraction.2994.36: The supervisor locks the statements first and skips the rows that others hold."""
    statement_id, run_id = await _run_of_statement(
        db, test_user, status=BankStatementStatus.PARSING, file_hash="lock-1"
    )
    await fail_run(db, run_id, error_code="storage_error", error_message="Failed.")
    await db.commit()
    maker = create_session_maker_from_db(db)

    async with maker() as holder:
        await holder.execute(
            select(StatementSummary.id).where(StatementSummary.id == statement_id).with_for_update(key_share=True)
        )
        count = await asyncio.wait_for(supervisor.reap_stale_parsing_runs(maker), timeout=5)
        status_while_held = (await _statement(db, statement_id)).status
        await holder.rollback()

    assert count == 0
    assert status_while_held is BankStatementStatus.PARSING
    assert await supervisor.reap_stale_parsing_runs(maker) == 1
    assert (await _statement(db, statement_id)).status is BankStatementStatus.REJECTED


async def test_AC_extraction_2994_37_the_failure_report_locks_the_statement_before_the_run(db, test_user, monkeypatch):
    """AC-extraction.2994.37: A failure report and the reaper take the statement lock first, so they cannot deadlock."""
    from src.extraction.extension import statement_parsing

    statement_id, run_id = await _run_of_statement(
        db, test_user, status=BankStatementStatus.PARSING, file_hash="order-1"
    )
    job = ParseJob(
        statement_id=statement_id,
        run_id=run_id,
        filename="order.csv",
        institution="DBS",
        user_id=test_user.id,
        account_id=None,
        file_hash="order-1",
        storage_key="statements/order.csv",
        model=None,
    )
    maker = create_session_maker_from_db(db)
    swallowed: list[tuple] = []
    monkeypatch.setattr(statement_parsing.logger, "exception", lambda *args, **_kwargs: swallowed.append(args))

    async def report_failure() -> None:
        async with maker() as session:
            statement = await session.get(StatementSummary, statement_id)
            await handle_parse_failure(statement, session, job=job, message="late", error_type="ExtractionError")

    async with maker() as reaper:
        await reaper.execute(
            select(StatementSummary.id).where(StatementSummary.id == statement_id).with_for_update(key_share=True)
        )
        reporter = asyncio.create_task(report_failure())
        await asyncio.sleep(1.0)
        assert await reap_stale_runs(reaper, now=datetime.now(UTC) + timedelta(minutes=10)) == [run_id]
        await reaper.commit()
    await asyncio.wait_for(reporter, timeout=10)

    assert swallowed == [], "the failure report was the victim of a deadlock"
    (run,) = await _runs(db, statement_id)
    assert (run.state, run.error_code) == (RunState.FAILED, "heartbeat_lost")
    assert (await _statement(db, statement_id)).status is BankStatementStatus.PARSING


async def test_AC_extraction_2994_32_the_supervisor_loop_calls_the_run_reaper(monkeypatch):
    """AC-extraction.2994.32: Each tick of the supervisor loop reaps stale runs and keeps going after an error."""
    stop_event = asyncio.Event()
    calls: list[int] = []

    async def failing_then_stopping_reaper(sessionmaker=None) -> int:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("reaper failure")
        stop_event.set()
        return 0

    monkeypatch.setattr(supervisor, "reap_stale_parsing_runs", failing_then_stopping_reaper)
    monkeypatch.setattr(supervisor, "PARSING_SUPERVISOR_INTERVAL_SECONDS", 0.01)

    await supervisor.run_parsing_supervisor(stop_event)

    assert len(calls) == 2
