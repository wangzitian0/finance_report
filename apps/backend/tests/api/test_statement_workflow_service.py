'AC25.2.1 EPIC-025'; from types import SimpleNamespace; from uuid import uuid4; import src.routers.statements as statements_router; from src.extraction.base.source_vocabulary import BankStatementStatus; from src.extraction.base.types import StatementPostingStatus; from src.extraction.extension import statement_workflow
class _FakeResult:
    def __init__(self, value: object) -> None: self._value = value
    def scalar_one_or_none(self) -> object: return self._value
class _FakeSession:
    def __init__(self, calls: list) -> None: self._calls = calls
    async def execute(self, statement: object, params: dict | None=None) -> _FakeResult | None:
        if 'pg_advisory_xact_lock' in str(statement): assert params is not None; self._calls.append(('release_lock', params['key'])); return None
        self._calls.append(('read_status',)); return _FakeResult(BankStatementStatus.PARSED)
    async def commit(self) -> None: self._calls.append(('commit',))
    async def refresh(self, obj: object) -> None: self._calls.append(('refresh', obj))
async def test_statement_workflow_service(monkeypatch):
    'AC-extraction.2502.1 AC25.2.1'; statement_id = uuid4(); user_id = uuid4(); approve_calls: list = []; approved_statement = SimpleNamespace(id=statement_id, name='approved')
    async def fake_approve(db, sid, uid): assert (sid, uid) == (statement_id, user_id); approve_calls.append(('approve_statement',)); return approved_statement
    async def fake_post(db, statement, uid, *, dependencies): assert statement is approved_statement; assert dependencies is posting_dependencies; approve_calls.append(('auto_post',)); return SimpleNamespace(created_count=3, status=StatementPostingStatus.POSTED)
    async def fake_opening(db, statement, uid, *, dependencies): assert statement is approved_statement; assert uid == user_id; assert dependencies is posting_dependencies; approve_calls.append(('opening_stock',))
    monkeypatch.setattr(statement_workflow, 'try_auto_post_statement_opening_balance', fake_opening); monkeypatch.setattr(statement_workflow, 'approve_statement', fake_approve); monkeypatch.setattr(statement_workflow, 'auto_create_posted_entries_for_statement', fake_post); posting_dependencies = object(); outcome = await statement_workflow.approve_statement_workflow(_FakeSession(approve_calls), statement_id, user_id, dependencies=posting_dependencies); assert outcome.created_count == 3; assert approve_calls == [('approve_statement',), ('auto_post',), ('opening_stock',), ('commit',)]; reject_calls: list = []; rejected_statement = SimpleNamespace(id=statement_id, name='rejected')
    async def fake_reject(db, sid, uid, *, reason): assert (sid, uid, reason) == (statement_id, user_id, 'looks wrong'); reject_calls.append(('reject_statement',)); return rejected_statement
    monkeypatch.setattr(statement_workflow, 'reject_statement', fake_reject); result = await statement_workflow.reject_statement_workflow(_FakeSession(reject_calls), statement_id, user_id, reason='looks wrong'); assert result is rejected_statement; assert reject_calls == [('read_status',), ('reject_statement',), ('release_lock', f'statement-release:{user_id}'), ('commit',), ('refresh', rejected_statement)]; assert statements_router.approve_statement_workflow is statement_workflow.approve_statement_workflow; assert statements_router.reject_statement_workflow is statement_workflow.reject_statement_workflow; assert not hasattr(statements_router, 'approve_statement_svc'); assert not hasattr(statements_router, 'reject_statement_svc')

# --- #2970: the planner statistics refresh runs after the response, in one background task ---
import asyncio
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
import structlog.testing
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.extraction import TransactionDirection
from src.extraction.orm.statement_summary import StatementSummary
from tests.factories import seed_parsed_statement
from tests.integration.test_statement_corpus_journeys import attach_reviewed_corpus_semantics

WAIT_SECONDS = 5  # Upper bound for a wait. A regression fails by name; it never hangs the run.


class _Runner:
    """Stands in for ``analyze_tenant_tables``: counts runs, blocks until ``release`` is set, can fail."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.runs = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.error = error

    async def __call__(self, *_args: object) -> None:
        self.runs += 1
        self.started.set()
        await self.release.wait()
        if self.error is not None:
            raise self.error


class _PostgresSession:
    """Request session fake: records the commits and reports the PostgreSQL dialect."""

    def __init__(self, calls: list, dialect: str = "postgresql") -> None:
        self._calls = calls
        self._dialect = dialect

    def get_bind(self) -> SimpleNamespace:
        return SimpleNamespace(dialect=SimpleNamespace(name=self._dialect))

    async def commit(self) -> None:
        self._calls.append(("commit",))


class _RecordingSession:
    """Refresh session fake: records every SQL text and the commit."""

    def __init__(self, statements: list[str]) -> None:
        self.statements = statements

    async def __aenter__(self) -> "_RecordingSession":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def execute(self, statement: object, params: dict | None = None) -> None:
        self.statements.append(str(statement))

    async def commit(self) -> None:
        self.statements.append("COMMIT")


@pytest_asyncio.fixture
async def production_like(monkeypatch):
    """Leave the testing environment, so that the refresh is requested. The gap between two runs is 0 s."""
    monkeypatch.setattr(statement_workflow.settings, "environment", "staging")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setattr(statement_workflow, "TENANT_STATISTICS_MIN_GAP_SECONDS", 0, raising=False)
    monkeypatch.setattr(statement_workflow, "_refresh_task", None, raising=False)
    monkeypatch.setattr(statement_workflow, "_refresh_requested", False, raising=False)
    yield
    task = statement_workflow._refresh_task
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _wait_until_started(runner: _Runner) -> None:
    await asyncio.wait_for(runner.started.wait(), WAIT_SECONDS)


async def _until(condition) -> None:
    while not condition():
        await asyncio.sleep(0)


async def _wait_until_idle() -> None:
    """Wait until the background task has ended."""
    task = statement_workflow._refresh_task
    if task is not None:
        await asyncio.wait_for(task, WAIT_SECONDS)


def _patch_approval(monkeypatch, calls: list) -> SimpleNamespace:
    statement = SimpleNamespace(status=BankStatementStatus.APPROVED)

    async def approve(db, statement_id, user_id):
        calls.append(("approve_statement",))
        return statement

    async def post(db, statement, user_id, *, dependencies):
        calls.append(("auto_post",))
        return SimpleNamespace(created_count=2, status=StatementPostingStatus.POSTED)

    async def opening(db, statement, user_id, *, dependencies):
        calls.append(("opening_balance",))

    monkeypatch.setattr(statement_workflow, "approve_statement", approve)
    monkeypatch.setattr(statement_workflow, "auto_create_posted_entries_for_statement", post)
    monkeypatch.setattr(statement_workflow, "try_auto_post_statement_opening_balance", opening)
    return statement


async def test_AC_extraction_2970_1_approve_returns_while_the_refresh_is_pending(production_like, monkeypatch):
    'AC-extraction.2970.1'
    runner = _Runner()
    monkeypatch.setattr(statement_workflow, "analyze_tenant_tables", runner)
    calls: list = []
    _patch_approval(monkeypatch, calls)

    try:
        outcome = await asyncio.wait_for(
            statement_workflow.approve_statement_workflow(
                _PostgresSession(calls), uuid4(), uuid4(), dependencies=object()
            ),
            WAIT_SECONDS,
        )
    except TimeoutError:
        pytest.fail("approve_statement_workflow waited for the blocked statistics refresh")

    assert outcome.created_count == 2
    await _wait_until_started(runner)
    task = statement_workflow._refresh_task
    assert task is not None and not task.done(), "the refresh must still run, and the module must hold its task"
    assert calls == [("approve_statement",), ("auto_post",), ("opening_balance",), ("commit",)]  # one commit only
    runner.release.set()
    await _wait_until_idle()
    assert runner.runs == 1
    assert calls.count(("commit",)) == 1


async def test_AC_extraction_2970_1_a_failed_refresh_leaves_the_approval_committed(
    production_like, monkeypatch, client, db, test_user
):
    'AC-extraction.2970.1'
    runner = _Runner(error=RuntimeError("tuple concurrently updated"))
    runner.release.set()
    monkeypatch.setattr(statement_workflow, "analyze_tenant_tables", runner)
    rows = [
        {"description": "Salary", "amount": Decimal("2500.00"), "direction": TransactionDirection.IN, "date": date(2026, 1, 1)},
        {"description": "Rent", "amount": Decimal("12.50"), "direction": TransactionDirection.OUT, "date": date(2026, 1, 2)},
    ]
    seeded = await seed_parsed_statement(db, test_user.id, original_filename="refresh_failure.pdf", transactions=rows)
    seeded.statement.period_start = rows[0]["date"]
    seeded.statement.period_end = rows[-1]["date"]
    await attach_reviewed_corpus_semantics(db, test_user.id, seeded.transactions)
    await db.commit()
    statement_id = seeded.id

    with structlog.testing.capture_logs() as logs:
        response = await client.post(f"/statements/{statement_id}/review/approve", json={"create_account_if_missing": True})
        await _wait_until_idle()

    assert response.status_code == 200, response.text
    assert runner.runs == 1
    status = await db.scalar(select(StatementSummary.status).where(StatementSummary.id == statement_id))
    assert status == BankStatementStatus.APPROVED
    failures = [entry for entry in logs if entry["event"] == "statement.statistics_refresh.failed"]
    assert len(failures) == 1
    assert failures[0]["log_level"] == "warning"
    assert failures[0]["error_type"] == "RuntimeError"


async def test_AC_extraction_2970_1_five_requests_during_one_run_cause_one_more_run(production_like, monkeypatch):
    'AC-extraction.2970.1'
    runner = _Runner()
    monkeypatch.setattr(statement_workflow, "analyze_tenant_tables", runner)
    session = _PostgresSession([])

    statement_workflow.request_tenant_statistics_refresh(session)
    await _wait_until_started(runner)
    for _ in range(5):
        statement_workflow.request_tenant_statistics_refresh(session)
    for _ in range(3):
        await asyncio.sleep(0)  # Yield to the event loop: a second task would start its run now.
    assert runner.runs == 1, "a request during a run must not start a second run"

    runner.release.set()
    await _wait_until_idle()
    assert runner.runs == 2, "the five requests cause exactly one more run"


async def test_AC_extraction_2970_1_the_gap_separates_two_runs(production_like, monkeypatch):
    'AC-extraction.2970.1'
    events: list[str] = []
    gate = asyncio.Event()
    real_sleep = asyncio.sleep

    async def runner(*_args: object) -> None:
        events.append("run")
        await gate.wait()

    async def sleep(delay: float) -> None:
        if delay == 7:
            events.append("gap")
        await real_sleep(0)

    monkeypatch.setattr(statement_workflow, "analyze_tenant_tables", runner)
    monkeypatch.setattr(statement_workflow, "TENANT_STATISTICS_MIN_GAP_SECONDS", 7)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    session = _PostgresSession([])

    statement_workflow.request_tenant_statistics_refresh(session)
    await asyncio.wait_for(_until(lambda: events == ["run"]), WAIT_SECONDS)
    statement_workflow.request_tenant_statistics_refresh(session)
    gate.set()
    await _wait_until_idle()

    assert events == ["run", "gap", "run", "gap"]


async def test_AC_extraction_2970_1_the_refresh_session_sets_both_timeouts_before_analyze():
    'AC-extraction.2970.1'
    statements: list[str] = []

    await statement_workflow.analyze_tenant_tables(lambda: _RecordingSession(statements))

    assert statements == [
        "SET LOCAL lock_timeout = '2s'",
        "SET LOCAL statement_timeout = '20s'",
        f"ANALYZE {', '.join(statement_workflow.TENANT_ANALYZE_TABLES)}",
        "COMMIT",
    ]


@pytest.mark.parametrize(
    ("setting_environment", "process_environment", "dialect"),
    [("testing", "staging", "postgresql"), ("staging", "testing", "postgresql"), ("staging", "staging", "sqlite")],
    ids=["testing-setting", "testing-process-variable", "not-postgresql"],
)
async def test_AC_extraction_2970_1_no_refresh_task_in_the_testing_environment_or_without_postgresql(
    production_like, monkeypatch, setting_environment, process_environment, dialect
):
    'AC-extraction.2970.1'
    runner = _Runner()
    runner.release.set()
    monkeypatch.setattr(statement_workflow, "analyze_tenant_tables", runner)
    monkeypatch.setattr(statement_workflow.settings, "environment", setting_environment)
    monkeypatch.setenv("ENVIRONMENT", process_environment)

    statement_workflow.request_tenant_statistics_refresh(_PostgresSession([], dialect))
    await asyncio.sleep(0)  # A task that was created would run now.

    assert statement_workflow._refresh_task is None
    assert runner.runs == 0


async def test_AC_extraction_2970_1_a_failed_run_does_not_end_the_refresh(production_like, monkeypatch):
    'AC-extraction.2970.1'
    runner = _Runner(error=RuntimeError("tuple concurrently updated"))
    monkeypatch.setattr(statement_workflow, "analyze_tenant_tables", runner)
    session = _PostgresSession([])

    statement_workflow.request_tenant_statistics_refresh(session)
    await _wait_until_started(runner)
    statement_workflow.request_tenant_statistics_refresh(session)  # arrives during the run that fails
    runner.release.set()
    await _wait_until_idle()
    assert runner.runs == 2, "the request that arrived before the failure still gets its run, and the failure adds none"

    statement_workflow.request_tenant_statistics_refresh(session)  # arrives after the task ended
    await _wait_until_idle()
    assert runner.runs == 3, "a later request starts a new refresh after a failure"


async def test_AC_extraction_2970_1_a_lock_held_by_another_session_ends_the_refresh_at_the_lock_timeout(
    db_engine, monkeypatch
):
    'AC-extraction.2970.1'
    monkeypatch.setattr(statement_workflow, "TENANT_STATISTICS_LOCK_TIMEOUT", "100ms")
    maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as holder:
        await holder.execute(text("LOCK TABLE journal_entries IN ACCESS EXCLUSIVE MODE"))
        with pytest.raises(DBAPIError) as raised:
            await asyncio.wait_for(statement_workflow.analyze_tenant_tables(maker), WAIT_SECONDS)

    assert "lock timeout" in str(raised.value)
