"""Statement run record and its state module (#2994, phase A).

A run is one row per extraction or classification attempt. The partial unique index and the
conditional UPDATE in `statement_runs.py` are the only guards: no lock, no flag, no pre-check read.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from structlog.testing import capture_logs
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from src.audit import TraceResult, canonical_json_digest
from src.audit.orm import TraceRecordRow
from src.database import create_session_maker_from_db
from src.extraction import (
    ActiveRunExists,
    BankStatementStatus,
    RunActorKind,
    RunHints,
    RunKind,
    RunState,
    RunTrigger,
    StaleRun,
    StatementSummary,
    claim_run,
    create_run,
    fail_run,
    finish_run,
    get_active_run,
    heartbeat_run,
    reap_stale_runs,
)
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.extraction.orm.statement_run import StatementRun
from tests.factories import StatementSummaryFactory

HINTS = RunHints(keywords=["DBS", "savings"], note="Interest lines are credits.\nThe year is 2026.")
PROMPT_DIGEST = "c" * 64
BACKEND_DIR = Path(__file__).resolve().parents[2]
PRIOR_REVISION = "0073_stmt_gin_trace_trig_perf"
RUNS_REVISION = "0074_statement_runs"


async def _statement(db, user, *, status=BankStatementStatus.PARSING, created_at=None) -> StatementSummary:
    statement = StatementSummaryFactory.build(
        id=uuid4(),
        user_id=user.id,
        account_id=None,
        file_hash=f"runs-{uuid4()}",
        institution="DBS",
        status=status,
        confidence_score=None,
        balance_validated=None,
    )
    if created_at is not None:
        statement.created_at = created_at
    db.add(statement)
    await db.commit()
    return statement


async def _create(db, statement, **overrides) -> StatementRun:
    arguments = {
        "statement_id": statement.id,
        "user_id": statement.user_id,
        "kind": RunKind.EXTRACT,
        "actor_kind": RunActorKind.SYSTEM,
        "trigger": RunTrigger.UPLOAD,
        "hints": RunHints(),
    }
    run = await create_run(db, **{**arguments, **overrides})
    await db.commit()
    return run


async def _running(db, statement, **overrides) -> StatementRun:
    run = await _create(db, statement, **overrides)
    run = await claim_run(db, run.id)
    await db.commit()
    return run


async def _traces(db, statement_id: UUID, run_id: UUID) -> list[TraceRecordRow]:
    execution_id = f"statement:{statement_id}:run:{run_id}"
    rows = await db.execute(
        select(TraceRecordRow).where(TraceRecordRow.execution_id == execution_id).order_by(TraceRecordRow.occurred_at)
    )
    return list(rows.scalars())


async def _result_row(db, statement) -> StatementExtractionResultRecord:
    row = StatementExtractionResultRecord(
        user_id=statement.user_id,
        statement_id=statement.id,
        content_digest="a" * 64,
        source_content_digest="b" * 64,
        schema_version="2",
        producer_version="test",
        payload={},
        source_trace_record_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    db.add(row)
    await db.commit()
    return row


async def _run_count(db, statement_id: UUID) -> int:
    return await db.scalar(select(func.count()).select_from(StatementRun).where(StatementRun.statement_id == statement_id))


async def test_AC_extraction_2994_1_a_second_active_run_for_one_statement_raises_active_run_exists(db, test_user):
    """AC-extraction.2994.1: One statement holds at most one requested or running run."""
    statement = await _statement(db, test_user)
    first = await _create(db, statement)

    with pytest.raises(ActiveRunExists) as same_session:
        await create_run(
            db,
            statement_id=statement.id,
            user_id=test_user.id,
            kind=RunKind.EXTRACT,
            actor_kind=RunActorKind.USER,
            trigger=RunTrigger.RERUN,
            hints=HINTS,
        )
    assert same_session.value.active_run_id == first.id
    assert await _run_count(db, statement.id) == 1
    assert (await get_active_run(db, statement.id)).id == first.id

    await claim_run(db, first.id)
    await db.commit()
    with pytest.raises(ActiveRunExists):
        await _create(db, statement, trigger=RunTrigger.RERUN)

    await fail_run(db, first.id, error_code="provider_timeout", error_message="The model call timed out.")
    await db.commit()
    assert await get_active_run(db, statement.id) is None
    second = await _create(db, statement, trigger=RunTrigger.RERUN)
    assert second.seq == 2

    other = await _statement(db, test_user)
    other_run = await _create(db, other)
    assert other_run.seq == 1

    race = await _statement(db, test_user)
    maker = create_session_maker_from_db(db)

    async def create_in_own_session():
        async with maker() as session:
            try:
                run = await create_run(
                    session,
                    statement_id=race.id,
                    user_id=race.user_id,
                    kind=RunKind.EXTRACT,
                    actor_kind=RunActorKind.USER,
                    trigger=RunTrigger.RERUN,
                    hints=RunHints(),
                )
                await session.commit()
                return run
            except ActiveRunExists as exc:
                await session.rollback()
                return exc

    outcomes = await asyncio.gather(create_in_own_session(), create_in_own_session())
    winners = [outcome for outcome in outcomes if isinstance(outcome, StatementRun)]
    losers = [outcome for outcome in outcomes if isinstance(outcome, ActiveRunExists)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert losers[0].active_run_id == winners[0].id
    assert await _run_count(db, race.id) == 1


async def test_AC_extraction_2994_2_two_concurrent_claims_give_one_winner_and_one_stale_run(db, test_user):
    """AC-extraction.2994.2: A conditional UPDATE lets exactly one of two workers claim a requested run."""
    maker = create_session_maker_from_db(db)

    async def claim_in_own_session(run_id: UUID):
        async with maker() as session:
            try:
                run = await claim_run(session, run_id)
                await session.commit()
                return run
            except StaleRun as exc:
                await session.rollback()
                return exc

    for _round in range(5):
        statement = await _statement(db, test_user)
        run = await _create(db, statement)
        outcomes = await asyncio.gather(claim_in_own_session(run.id), claim_in_own_session(run.id))

        winners = [outcome for outcome in outcomes if isinstance(outcome, StatementRun)]
        losers = [outcome for outcome in outcomes if isinstance(outcome, StaleRun)]
        assert len(winners) == 1, outcomes
        assert len(losers) == 1, outcomes
        assert winners[0].state is RunState.RUNNING
        stored = await db.scalar(
            select(StatementRun).where(StatementRun.id == run.id).execution_options(populate_existing=True)
        )
        assert stored.state is RunState.RUNNING
        assert stored.started_at == winners[0].started_at
        running_records = [row for row in await _traces(db, statement.id, run.id) if row.assertion_id == "extract.running"]
        assert len(running_records) == 1


async def test_AC_extraction_2994_3_a_finish_after_the_reaper_failed_the_run_changes_nothing(db, test_user):
    """AC-extraction.2994.3: A late finish cannot overwrite a run that the reaper failed (#2960)."""
    statement = await _statement(db, test_user)
    run = await _running(db, statement)
    reaped_at = run.heartbeat_at + timedelta(minutes=6)

    assert await reap_stale_runs(db, now=reaped_at) == [run.id]
    await db.commit()
    result = await _result_row(db, statement)
    with pytest.raises(StaleRun):
        await finish_run(db, run.id, extraction_result_id=result.id, result_summary={"rows": 3})

    stored = await db.scalar(
        select(StatementRun).where(StatementRun.id == run.id).execution_options(populate_existing=True)
    )
    assert stored.state is RunState.FAILED
    assert stored.error_code == "heartbeat_lost"
    assert stored.finished_at == reaped_at
    assert stored.extraction_result_id is None
    assert stored.result_summary == {"retryable": True}
    records = await _traces(db, statement.id, run.id)
    assert [row.assertion_id for row in records] == ["extract.requested", "extract.running", "extract.failed"]
    assert records[-1].result is TraceResult.FAIL
    assert records[-1].reason_code == "run_failed.heartbeat_lost"
    assert records[-1].occurred_at == reaped_at


async def test_AC_extraction_2994_4_the_reaper_fails_only_runs_with_an_old_heartbeat(db, test_user):
    """AC-extraction.2994.4: The reaper fails a running run only when its heartbeat is older than the threshold."""
    now = datetime(2026, 11, 12, 8, 0, tzinfo=UTC)
    stale_after = timedelta(minutes=5)

    async def running_with_heartbeat_age(age: timedelta) -> StatementRun:
        run = await _running(db, await _statement(db, test_user))
        await db.execute(update(StatementRun).where(StatementRun.id == run.id).values(heartbeat_at=now - age))
        await db.commit()
        return run

    old = await running_with_heartbeat_age(timedelta(minutes=6))
    fresh = await running_with_heartbeat_age(timedelta(minutes=2))
    at_threshold = await running_with_heartbeat_age(stale_after)
    never_claimed = await _create(db, await _statement(db, test_user))
    finished = await _running(db, await _statement(db, test_user))
    await finish_run(db, finished.id)
    await db.execute(update(StatementRun).where(StatementRun.id == finished.id).values(heartbeat_at=now - timedelta(hours=1)))
    await db.commit()

    failed_ids = await reap_stale_runs(db, stale_after=stale_after, now=now)
    await db.commit()

    assert failed_ids == [old.id]

    async def stored(run: StatementRun) -> StatementRun:
        return await db.scalar(
            select(StatementRun).where(StatementRun.id == run.id).execution_options(populate_existing=True)
        )

    assert (await stored(old)).state is RunState.FAILED
    assert (await stored(old)).error_code == "heartbeat_lost"
    assert (await stored(old)).finished_at == now
    assert (await stored(fresh)).state is RunState.RUNNING
    assert (await stored(at_threshold)).state is RunState.RUNNING
    assert (await stored(never_claimed)).state is RunState.REQUESTED
    assert (await stored(finished)).state is RunState.SUCCEEDED
    assert await reap_stale_runs(db, stale_after=stale_after, now=now) == []


@pytest.mark.parametrize("actor", list(RunActorKind), ids=lambda actor: actor.value)
async def test_AC_extraction_2994_5_user_ai_and_system_actors_give_the_same_transition_sequence(db, test_user, actor):
    """AC-extraction.2994.5: The state functions follow one path for every actor kind."""
    statement = await _statement(db, test_user)
    result = await _result_row(db, statement)

    run = await create_run(
        db,
        statement_id=statement.id,
        user_id=test_user.id,
        kind=RunKind.EXTRACT,
        actor_kind=actor,
        trigger=RunTrigger.RERUN,
        hints=HINTS,
    )
    states = [run.state]
    await db.commit()
    states.append((await claim_run(db, run.id)).state)
    await db.commit()
    assert await heartbeat_run(db, run.id) is True
    await db.commit()
    states.append((await finish_run(db, run.id, extraction_result_id=result.id)).state)
    await db.commit()

    assert states == [RunState.REQUESTED, RunState.RUNNING, RunState.SUCCEEDED]
    assert run.actor_kind is actor
    records = await _traces(db, statement.id, run.id)
    assert [(row.assertion_kind, row.assertion_id, row.result, row.reason_code) for row in records] == [
        ("statement_run_transition", "extract.requested", TraceResult.PASS, f"run_requested.{actor.value}.rerun"),
        ("statement_run_transition", "extract.running", TraceResult.PASS, "run_running"),
        ("statement_run_transition", "extract.succeeded", TraceResult.PASS, "run_succeeded"),
    ]


async def test_AC_extraction_2994_6_a_run_with_hints_and_an_identical_result_keeps_its_own_row(db, test_user):
    """AC-extraction.2994.6: Two runs that end in the same result leave two rows with their own hints."""
    statement = await _statement(db, test_user)
    result = await _result_row(db, statement)

    first = await _running(db, statement)
    await finish_run(db, first.id, extraction_result_id=result.id)
    await db.commit()
    second = await _running(db, statement, actor_kind=RunActorKind.USER, trigger=RunTrigger.RERUN, hints=HINTS)
    await finish_run(db, second.id, extraction_result_id=result.id)
    await db.commit()

    rows = list(
        (
            await db.execute(
                select(StatementRun)
                .where(StatementRun.statement_id == statement.id)
                .order_by(StatementRun.seq)
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )
    assert [row.seq for row in rows] == [1, 2]
    assert [row.state for row in rows] == [RunState.SUCCEEDED, RunState.SUCCEEDED]
    assert [row.extraction_result_id for row in rows] == [result.id, result.id]
    assert rows[0].hints == {"keywords": [], "note": None}
    assert rows[1].hints == HINTS.model_dump(mode="json")
    assert [row.actor_kind for row in rows] == [RunActorKind.SYSTEM, RunActorKind.USER]
    for row in rows:
        assert len(await _traces(db, statement.id, row.id)) == 3


async def test_AC_extraction_2994_7_the_requested_trace_record_binds_hints_actor_and_the_transition_time(db, test_user):
    """AC-extraction.2994.7: The requested record pins the hints, actor and inputs and holds the real time."""
    statement = await _statement(db, test_user, created_at=datetime.now(UTC) - timedelta(days=2))
    parent = await _create(db, statement)
    await fail_run(db, parent.id, error_code="provider_timeout", error_message="The model call timed out.")
    await db.commit()

    before = datetime.now(UTC)
    run = await create_run(
        db,
        statement_id=statement.id,
        user_id=test_user.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.USER,
        trigger=RunTrigger.RERUN,
        hints=HINTS,
        model="provider/model-x",
        prompt_template_version="2",
        prompt_digest=PROMPT_DIGEST,
        parent_run_id=parent.id,
    )
    await db.commit()
    after = datetime.now(UTC)

    assert run.hints == HINTS.model_dump(mode="json")
    (record,) = await _traces(db, statement.id, run.id)
    assert record.execution_id == f"statement:{statement.id}:run:{run.id}"
    assert record.scope_id == str(test_user.id)
    assert record.target_kind == "statement_run"
    assert record.target_id == str(run.id)
    assert record.assertion_id == "extract.requested"
    assert record.reason_code == "run_requested.user.rerun"
    assert record.evidence_manifest_digest == canonical_json_digest(
        {
            "kind": "extract",
            "actor_kind": "user",
            "trigger": "rerun",
            "seq": 2,
            "hints": {"keywords": ["DBS", "savings"], "note": "Interest lines are credits.\nThe year is 2026."},
            "model": "provider/model-x",
            "prompt_template_version": "2",
            "prompt_digest": PROMPT_DIGEST,
            "parent_run_id": str(parent.id),
        }
    )
    assert record.occurred_at == run.requested_at
    assert before <= record.occurred_at <= after
    assert record.occurred_at - statement.created_at > timedelta(days=1)

    columns = TraceRecordRow.__table__.columns
    for column in columns:
        value = str(getattr(record, column.key))
        assert "Interest lines" not in value, f"hint text leaked into trace column {column.key}"
        assert "savings" not in value, f"hint text leaked into trace column {column.key}"

    other = await _statement(db, test_user)
    same_hints_other_actor = await _create(db, other, actor_kind=RunActorKind.AI, trigger=RunTrigger.RERUN, hints=HINTS)
    (other_record,) = await _traces(db, other.id, same_hints_other_actor.id)
    assert other_record.evidence_manifest_digest != record.evidence_manifest_digest


def _hints_cases_ok():
    many = [f"k{index}" for index in range(20)]
    return [
        pytest.param({}, {"keywords": [], "note": None}, id="empty"),
        pytest.param({"keywords": many}, {"keywords": many, "note": None}, id="20-keywords"),
        pytest.param({"keywords": ["x" * 64]}, {"keywords": ["x" * 64], "note": None}, id="64-char-keyword"),
        pytest.param(
            {"keywords": ["  " + "x" * 64 + "  "]}, {"keywords": ["x" * 64], "note": None}, id="64-char-keyword-padded"
        ),
        pytest.param(
            {"keywords": ["  dbs ", "\tsavings account\n"]},
            {"keywords": ["dbs", "savings account"], "note": None},
            id="keywords-lose-surrounding-space",
        ),
        pytest.param({"note": "n" * 500}, {"keywords": [], "note": "n" * 500}, id="500-char-note"),
        pytest.param(
            {"note": " first line\nsecond\tindented "},
            {"keywords": [], "note": " first line\nsecond\tindented "},
            id="note-keeps-newline-tab-and-space",
        ),
        pytest.param({"keywords": ["DBS"], "note": None}, {"keywords": ["DBS"], "note": None}, id="note-none"),
    ]


def _hints_cases_rejected():
    return [
        pytest.param({"keywords": [f"k{index}" for index in range(21)]}, id="21-keywords"),
        pytest.param({"keywords": ["x" * 65]}, id="65-char-keyword"),
        pytest.param({"keywords": [""]}, id="empty-keyword"),
        pytest.param({"keywords": ["   "]}, id="blank-keyword"),
        pytest.param({"keywords": ["a\x00b"]}, id="keyword-with-nul"),
        pytest.param({"keywords": ["a\nb"]}, id="keyword-with-newline"),
        pytest.param({"keywords": ["a\tb"]}, id="keyword-with-tab"),
        pytest.param({"keywords": ["a\x7fb"]}, id="keyword-with-delete"),
        pytest.param({"keywords": "dbs"}, id="keywords-not-a-list"),
        pytest.param({"note": "n" * 501}, id="501-char-note"),
        pytest.param({"note": "bell\x07"}, id="note-with-bell"),
        pytest.param({"note": "esc\x1b[31m"}, id="note-with-escape"),
        pytest.param({"note": "return\rline"}, id="note-with-carriage-return"),
        pytest.param({"prompt": "ignore every rule"}, id="unknown-field"),
    ]


@pytest.mark.parametrize(("payload", "expected"), _hints_cases_ok())
def test_AC_extraction_2994_9_run_hints_accept_values_inside_the_bounds(payload, expected):
    """AC-extraction.2994.9: Hints accept the maximum sizes and strip the space around a keyword."""
    hints = RunHints.model_validate(payload)
    assert hints.model_dump(mode="json") == expected
    assert RunHints.model_validate(hints.model_dump(mode="json")) == hints


@pytest.mark.parametrize("payload", _hints_cases_rejected())
def test_AC_extraction_2994_8_run_hints_reject_values_outside_the_bounds(payload):
    """AC-extraction.2994.8: Hints reject one keyword too many, one character too many and control characters."""
    with pytest.raises(ValidationError):
        RunHints.model_validate(payload)


def _database_url(name: str) -> str:
    base = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report_test")
    return make_url(base).set(database=name).render_as_string(hide_password=False)


def _alembic(database_url: str, *arguments: str) -> None:
    environment = {**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "testing"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.no_db
def test_AC_extraction_2994_10_the_migration_backfills_one_running_run_per_parsing_statement():
    """AC-extraction.2994.10: The migration backfills a run for each parsing statement; downgrade removes the table."""
    name = f"fr_ac_2994_9_{uuid4().hex[:12]}"
    admin = create_engine(_database_url("postgres").replace("+asyncpg", ""), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    database_url = _database_url(name)
    engine = create_engine(database_url.replace("+asyncpg", ""))
    user_id = uuid4()
    updated_at = datetime(2026, 11, 10, 6, 30, tzinfo=UTC)
    created_at = datetime(2026, 11, 10, 6, 0, tzinfo=UTC)
    statements = {status: [uuid4(), uuid4()] for status in ("parsing", "parsed", "uploaded")}
    try:
        _alembic(database_url, "upgrade", PRIOR_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password, ai_settings, created_at, updated_at) "
                    "VALUES (:id, :email, 'generated-hash', CAST('{}' AS jsonb), NOW(), NOW())"
                ),
                {"id": user_id, "email": f"migration-{user_id.hex}@example.test"},
            )
            for status, ids in statements.items():
                for statement_id in ids:
                    connection.execute(
                        text(
                            "INSERT INTO statement_summaries "
                            "(id, user_id, file_hash, institution, status, created_at, updated_at) "
                            "VALUES (:id, :user_id, :file_hash, 'DBS', "
                            "CAST(:status AS statement_summary_status_enum), :created_at, :updated_at)"
                        ),
                        {
                            "id": statement_id,
                            "user_id": user_id,
                            "file_hash": statement_id.hex,
                            "status": status,
                            "created_at": created_at,
                            "updated_at": updated_at,
                        },
                    )

        _alembic(database_url, "upgrade", RUNS_REVISION)
        select_runs = text(
            "SELECT statement_id, user_id, seq, kind::text, state::text, actor_kind::text, trigger::text, "
            "hints, heartbeat_at, started_at, requested_at, finished_at, parent_run_id, extraction_result_id, "
            "result_summary, error_code, error_message FROM statement_runs"
        )
        with engine.connect() as connection:
            rows = connection.execute(select_runs).all()
            assert {row.statement_id for row in rows} == set(statements["parsing"])
            assert len(rows) == 2
            for row in rows:
                assert row.user_id == user_id
                assert (row.seq, row.kind, row.state, row.actor_kind, row.trigger) == (
                    1,
                    "extract",
                    "running",
                    "system",
                    "upload",
                )
                assert row.hints == {}
                assert row.heartbeat_at == updated_at
                assert row.started_at == updated_at
                assert row.requested_at == created_at
                assert row.finished_at is None
                assert row.parent_run_id is None
                assert row.extraction_result_id is None
                assert row.result_summary is None
                assert row.error_code is None
                assert row.error_message is None
            types = {
                row[0]
                for row in connection.execute(text("SELECT typname FROM pg_type WHERE typtype = 'e' AND typname LIKE 'statement\\_run\\_%'"))
            }
            assert types == {
                "statement_run_kind_enum",
                "statement_run_state_enum",
                "statement_run_actor_kind_enum",
                "statement_run_trigger_enum",
            }

        insert_run = text(
            "INSERT INTO statement_runs (id, statement_id, user_id, seq, kind, state, actor_kind, trigger, hints, "
            "requested_at) VALUES (gen_random_uuid(), :statement_id, :user_id, :seq, 'extract', :state, 'user', "
            "'rerun', CAST('{}' AS jsonb), NOW())"
        )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert_run, {"statement_id": statements["parsing"][0], "user_id": user_id, "seq": 2, "state": "requested"}
            )
        with engine.begin() as connection:
            connection.execute(
                insert_run, {"statement_id": statements["parsed"][0], "user_id": user_id, "seq": 1, "state": "requested"}
            )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert_run, {"statement_id": statements["parsed"][0], "user_id": user_id, "seq": 1, "state": "failed"}
            )
        with engine.begin() as connection:
            connection.execute(
                insert_run, {"statement_id": statements["parsed"][0], "user_id": user_id, "seq": 2, "state": "failed"}
            )
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM statement_summaries WHERE id = :id"), {"id": statements["parsed"][0]})
            remaining = connection.execute(
                text("SELECT count(*) FROM statement_runs WHERE statement_id = :id"), {"id": statements["parsed"][0]}
            ).scalar_one()
            assert remaining == 0

        _alembic(database_url, "downgrade", PRIOR_REVISION)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT to_regclass('statement_runs')")).scalar_one() is None
            assert (
                connection.execute(text("SELECT count(*) FROM pg_type WHERE typtype = 'e' AND typname LIKE 'statement\\_run\\_%'")).scalar_one()
                == 0
            )
            assert connection.execute(text("SELECT count(*) FROM statement_summaries")).scalar_one() == 5

        _alembic(database_url, "upgrade", RUNS_REVISION)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM statement_runs")).scalar_one() == 2
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


async def test_AC_extraction_2994_11_each_transition_accepts_only_its_source_states(db, test_user):
    """AC-extraction.2994.11: A transition from a state that the function does not accept raises StaleRun."""
    statement = await _statement(db, test_user)
    run = await _create(db, statement)

    with pytest.raises(StaleRun):
        await finish_run(db, run.id)
    assert await heartbeat_run(db, run.id) is False

    await claim_run(db, run.id)
    await db.commit()
    with pytest.raises(StaleRun):
        await claim_run(db, run.id)
    assert await heartbeat_run(db, run.id) is True

    with pytest.raises(ValueError, match="error_code"):
        await fail_run(db, run.id, error_code="Not A Code", error_message="x")
    with pytest.raises(ValueError, match="error_message"):
        await fail_run(db, run.id, error_code="provider_timeout", error_message="x" * 501)
    failed = await fail_run(
        db, run.id, error_code="provider_timeout", error_message="x" * 500, retryable=True
    )
    await db.commit()
    assert failed.state is RunState.FAILED
    assert failed.result_summary == {"retryable": True}
    assert failed.finished_at is not None

    for late in (
        lambda: claim_run(db, run.id),
        lambda: finish_run(db, run.id),
        lambda: fail_run(db, run.id, error_code="provider_timeout", error_message="again"),
        lambda: claim_run(db, uuid4()),
    ):
        with pytest.raises(StaleRun):
            await late()
    assert await heartbeat_run(db, run.id) is False

    never_claimed = await _create(db, statement)
    skipped = await fail_run(db, never_claimed.id, error_code="dispatch_lost", error_message="No worker claimed the run.")
    await db.commit()
    assert skipped.state is RunState.FAILED
    assert skipped.started_at is None
    assert skipped.result_summary == {"retryable": False}
    assert skipped.seq == 2


async def test_AC_extraction_2994_12_the_logs_of_a_run_hold_a_digest_and_never_the_hint_text(db, test_user):
    """AC-extraction.2994.12: A transition logs the run id, kind, state, hints digest and keyword count only."""
    hints = RunHints(keywords=["zebra-keyword", "quartz-keyword"], note="needle-note-text for the model")
    statement = await _statement(db, test_user)

    with capture_logs() as logs:
        run = await _create(db, statement, hints=hints, actor_kind=RunActorKind.USER, trigger=RunTrigger.RERUN)
        await claim_run(db, run.id)
        await finish_run(db, run.id)
        await db.commit()
        other = await _running(db, await _statement(db, test_user))
        await fail_run(db, other.id, error_code="provider_timeout", error_message="The model call timed out.")
        await db.commit()

    transitions = [entry for entry in logs if entry["event"] == "statement.run.transition"]
    assert [(entry["run_id"], entry["state"]) for entry in transitions[:3]] == [
        (str(run.id), "requested"),
        (str(run.id), "running"),
        (str(run.id), "succeeded"),
    ]
    digest = canonical_json_digest(hints.model_dump(mode="json"))
    for entry in transitions[:3]:
        assert set(entry) == {"event", "log_level", "run_id", "kind", "state", "hints_digest", "hint_keyword_count"}
        assert entry["kind"] == "extract"
        assert entry["hints_digest"] == digest
        assert entry["hint_keyword_count"] == 2
    assert transitions[-1]["state"] == "failed"
    assert transitions[-1]["error_code"] == "provider_timeout"
    for hint_text in ("zebra-keyword", "quartz-keyword", "needle-note-text"):
        assert hint_text not in str(logs)

    with pytest.raises(IntegrityError) as missing_statement:
        await create_run(
            db,
            statement_id=uuid4(),
            user_id=test_user.id,
            kind=RunKind.EXTRACT,
            actor_kind=RunActorKind.USER,
            trigger=RunTrigger.RERUN,
            hints=hints,
        )
    assert "needle-note-text" not in str(missing_statement.value)
    assert "zebra-keyword" not in str(missing_statement.value)
