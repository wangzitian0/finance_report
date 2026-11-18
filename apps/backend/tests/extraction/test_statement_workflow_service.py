from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
import structlog.testing
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import src.routers.statements as statements_router
from src.extraction import TransactionDirection
from src.extraction.base.source_vocabulary import BankStatementStatus
from src.extraction.base.types import StatementPostingStatus
from src.extraction.extension import statement_workflow
from src.extraction.orm.statement_summary import StatementSummary
from tests.factories import seed_parsed_statement
from tests.integration.test_statement_corpus_journeys import attach_reviewed_corpus_semantics

WAIT_SECONDS = 5


class _FakeSession:
    def __init__(self, calls: list, dialect: str = "postgresql") -> None:
        self._calls, self._dialect = calls, dialect

    get_bind = lambda self: SimpleNamespace(dialect=SimpleNamespace(name=self._dialect))
    commit = AsyncMock(side_effect=lambda: None)

    async def execute(self, statement: object, params: dict | None = None):
        if "pg_advisory_xact_lock" in str(statement):
            self._calls.append(("release_lock", params["key"]))
            return None
        self._calls.append(("read_status",))
        return SimpleNamespace(scalar_one_or_none=lambda: BankStatementStatus.PARSED)

    async def flush(self) -> None:
        self._calls.append(("flush",))

    async def refresh(self, obj: object) -> None:
        self._calls.append(("refresh", obj))


class _Runner:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.runs, self.started, self.release, self.error = 0, asyncio.Event(), asyncio.Event(), error

    async def __call__(self, *_args: object) -> None:
        self.runs += 1
        self.started.set()
        await self.release.wait()
        if self.error is not None:
            raise self.error


@pytest_asyncio.fixture
async def production_like(monkeypatch):
    monkeypatch.setattr(statement_workflow.settings, "environment", "staging")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    for attr, val in [("TENANT_STATISTICS_MIN_GAP_SECONDS", 0), ("_refresh_task", None), ("_refresh_requested", False)]:
        monkeypatch.setattr(statement_workflow, attr, val)
    yield
    if statement_workflow._refresh_task is not None and not statement_workflow._refresh_task.done():
        statement_workflow._refresh_task.cancel()
        await asyncio.gather(statement_workflow._refresh_task, return_exceptions=True)


async def _wait_until_idle() -> None:
    await asyncio.wait_for(
        statement_workflow._refresh_task, WAIT_SECONDS
    ) if statement_workflow._refresh_task is not None else None


def _patch_approval(monkeypatch, calls: list, *, created_count: int = 2):
    stmt = SimpleNamespace(status=BankStatementStatus.APPROVED)
    monkeypatch.setattr(
        statement_workflow,
        "approve_statement_with_transactions",
        AsyncMock(side_effect=lambda *_a: (calls.append(("approve_statement",)), (stmt, ["txn-1"]))[1]),
    )
    monkeypatch.setattr(
        statement_workflow,
        "auto_create_posted_entries_for_statement",
        AsyncMock(
            side_effect=lambda *_a, **_kw: (
                calls.append(("auto_post",)),
                SimpleNamespace(created_count=created_count, status=StatementPostingStatus.POSTED),
            )[1]
        ),
    )
    monkeypatch.setattr(
        statement_workflow,
        "try_auto_post_statement_opening_balance",
        AsyncMock(side_effect=lambda *_a, **_kw: calls.append(("opening_balance",))),
    )


async def test_statement_workflow_service(monkeypatch):
    sid, uid, approve_calls, reject_calls = uuid4(), uuid4(), [], []
    session = _FakeSession(approve_calls)
    session.commit = AsyncMock(side_effect=lambda: approve_calls.append(("commit",)))
    _patch_approval(monkeypatch, approve_calls, created_count=3)
    outcome = await statement_workflow.approve_statement_workflow(
        session, sid, uid, dependencies=object(), base_currency="SGD"
    )
    assert outcome.created_count == 3 and approve_calls == [
        ("approve_statement",),
        ("auto_post",),
        ("opening_balance",),
        ("commit",),
    ]

    rejected_stmt = SimpleNamespace(id=sid, name="rejected")
    monkeypatch.setattr(
        statement_workflow,
        "reject_statement",
        AsyncMock(side_effect=lambda *_a, **_kw: (reject_calls.append(("reject_statement",)), rejected_stmt)[1]),
    )
    result = await statement_workflow.reject_statement_workflow(
        _FakeSession(reject_calls), sid, uid, reason="looks wrong", base_currency="SGD"
    )
    assert result is rejected_stmt and reject_calls == [
        ("read_status",),
        ("reject_statement",),
        ("release_lock", f"statement-release:{uid}"),
        ("flush",),
        ("refresh", rejected_stmt),
    ]
    assert (
        statements_router.approve_statement_workflow is statement_workflow.approve_statement_workflow
        and statements_router.reject_statement_workflow is statement_workflow.reject_statement_workflow
    )
    assert not hasattr(statements_router, "approve_statement_svc") and not hasattr(
        statements_router, "reject_statement_svc"
    )


async def test_AC_extraction_2970_1_approve_returns_while_the_refresh_is_pending(production_like, monkeypatch):
    runner, calls = _Runner(), []
    monkeypatch.setattr(statement_workflow, "analyze_tenant_tables", runner)
    _patch_approval(monkeypatch, calls)
    session = _FakeSession(calls)
    session.commit = AsyncMock(side_effect=lambda: calls.append(("commit",)))
    outcome = await asyncio.wait_for(
        statement_workflow.approve_statement_workflow(
            session, uuid4(), uuid4(), dependencies=object(), base_currency="SGD"
        ),
        WAIT_SECONDS,
    )
    await asyncio.wait_for(runner.started.wait(), WAIT_SECONDS)
    assert (
        outcome.created_count == 2
        and statement_workflow._refresh_task is not None
        and not statement_workflow._refresh_task.done()
        and calls == [("approve_statement",), ("auto_post",), ("opening_balance",), ("commit",)]
    )
    runner.release.set()
    await _wait_until_idle()
    assert runner.runs == 1 and calls.count(("commit",)) == 1


async def test_AC_extraction_2970_1_a_failed_refresh_leaves_the_approval_committed(
    production_like, monkeypatch, client, db, test_user
):
    runner = _Runner(error=RuntimeError("tuple concurrently updated"))
    runner.release.set()
    monkeypatch.setattr(statement_workflow, "analyze_tenant_tables", runner)
    rows = [
        {
            "description": "Salary",
            "amount": Decimal("2500.00"),
            "direction": TransactionDirection.IN,
            "date": date(2026, 1, 1),
        },
        {
            "description": "Rent",
            "amount": Decimal("12.50"),
            "direction": TransactionDirection.OUT,
            "date": date(2026, 1, 2),
        },
    ]
    seeded = await seed_parsed_statement(db, test_user.id, original_filename="refresh_failure.pdf", transactions=rows)
    seeded.statement.period_start, seeded.statement.period_end = rows[0]["date"], rows[-1]["date"]
    await attach_reviewed_corpus_semantics(db, test_user.id, seeded.transactions)
    await db.commit()
    with structlog.testing.capture_logs() as logs:
        response = await client.post(f"/statements/{seeded.id}/approvals", json={"create_account_if_missing": True})
        await _wait_until_idle()
    failures = [e for e in logs if e["event"] == "statement.statistics_refresh.failed"]
    assert (
        response.status_code == 200
        and runner.runs == 1
        and await db.scalar(select(StatementSummary.status).where(StatementSummary.id == seeded.id))
        == BankStatementStatus.APPROVED
    )
    assert len(failures) == 1 and (failures[0]["log_level"], failures[0]["error_type"]) == ("warning", "RuntimeError")


async def test_AC_extraction_2970_1_coalescing_and_failure_recovery(production_like, monkeypatch):
    for error, reqs_after, expected_runs in [(None, 0, 2), (RuntimeError("tuple concurrently updated"), 1, 3)]:
        runner = _Runner(error=error)
        monkeypatch.setattr(statement_workflow, "analyze_tenant_tables", runner)
        session = _FakeSession([])
        statement_workflow.request_tenant_statistics_refresh(session)
        await asyncio.wait_for(runner.started.wait(), WAIT_SECONDS)
        for _ in range(5):
            statement_workflow.request_tenant_statistics_refresh(session)
        await asyncio.sleep(0)
        assert runner.runs == 1
        runner.release.set()
        await _wait_until_idle()
        assert runner.runs == 2
        if reqs_after:
            statement_workflow.request_tenant_statistics_refresh(session)
            await _wait_until_idle()
            assert runner.runs == expected_runs


async def test_AC_extraction_2970_1_the_gap_separates_two_runs(production_like, monkeypatch):
    events, gate, real_sleep = [], asyncio.Event(), asyncio.sleep
    monkeypatch.setattr(statement_workflow, "analyze_tenant_tables", lambda *_a: (events.append("run"), gate.wait())[1])
    monkeypatch.setattr(statement_workflow, "TENANT_STATISTICS_MIN_GAP_SECONDS", 7)
    monkeypatch.setattr(asyncio, "sleep", lambda d: (events.append("gap") if d == 7 else None, real_sleep(0))[1])
    statement_workflow.request_tenant_statistics_refresh(_FakeSession([]))
    while events != ["run"]:
        await real_sleep(0)
    statement_workflow.request_tenant_statistics_refresh(_FakeSession([]))
    gate.set()
    await _wait_until_idle()
    assert events == ["run", "gap", "run", "gap"]


async def test_AC_extraction_2970_1_the_refresh_session_sets_both_timeouts_before_analyze():
    stmts: list[str] = []

    class Rec:
        async def __aenter__(self):
            return self

        __aexit__ = AsyncMock(return_value=None)
        execute = AsyncMock(side_effect=lambda s, params=None: stmts.append(str(s)))
        commit = AsyncMock(side_effect=lambda: stmts.append("COMMIT"))

    await statement_workflow.analyze_tenant_tables(Rec)
    assert stmts == [
        "SET LOCAL lock_timeout = '2s'",
        "SET LOCAL statement_timeout = '20s'",
        f"ANALYZE {', '.join(statement_workflow.TENANT_ANALYZE_TABLES)}",
        "COMMIT",
    ]


@pytest.mark.parametrize(
    ("setting_env", "process_env", "dialect"),
    [("testing", "staging", "postgresql"), ("staging", "testing", "postgresql"), ("staging", "staging", "sqlite")],
    ids=["testing-setting", "testing-process-variable", "not-postgresql"],
)
async def test_AC_extraction_2970_1_no_refresh_task_in_testing_or_non_postgres(
    production_like, monkeypatch, setting_env, process_env, dialect
):
    runner = _Runner()
    runner.release.set()
    monkeypatch.setattr(statement_workflow, "analyze_tenant_tables", runner)
    monkeypatch.setattr(statement_workflow.settings, "environment", setting_env)
    monkeypatch.setenv("ENVIRONMENT", process_env)
    statement_workflow.request_tenant_statistics_refresh(_FakeSession([], dialect))
    await asyncio.sleep(0)
    assert statement_workflow._refresh_task is None and runner.runs == 0


async def test_AC_extraction_2970_1_a_lock_held_by_another_session_ends_at_lock_timeout(db_engine, monkeypatch):
    monkeypatch.setattr(statement_workflow, "TENANT_STATISTICS_LOCK_TIMEOUT", "100ms")
    maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as holder:
        await holder.execute(text("LOCK TABLE journal_entries IN ACCESS EXCLUSIVE MODE"))
        with pytest.raises(DBAPIError, match="lock timeout"):
            await asyncio.wait_for(statement_workflow.analyze_tenant_tables(maker), WAIT_SECONDS)
