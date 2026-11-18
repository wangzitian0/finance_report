"""Statement run record and its state module (#2994, phase A)."""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.audit import TraceResult, canonical_json_digest
from src.audit.orm import TraceRecordRow
from src.database import create_session_maker_from_db
from src.extraction import (
    ActiveRunExists,
    RunActorKind,
    RunHints,
    RunKind,
    RunState,
    RunTrigger,
    StaleRun,
    claim_run,
    create_run,
    fail_run,
    finish_run,
    get_active_run,
    heartbeat_run,
    reap_stale_runs,
)
from src.extraction.orm.statement_run import StatementRun
from tests.extraction._statement_run_helpers import (
    _runs,
    claim_test_run,
    create_test_run,
    get_run,
    make_result_record,
    make_run_statement,
    run_claim_race,
    run_create_race,
    run_traces,
    verify_reaper_threshold_case,
    verify_run_logging_digest,
    verify_run_transitions_guard,
    verify_runs_migration_backfill,
    verify_worker_retry_reaper_and_user_start,
)

HINTS = RunHints(keywords=["DBS", "savings"], note="Interest lines are credits.\nThe year is 2026.")
PROMPT_DIGEST = "c" * 64


async def test_AC_extraction_2994_1_a_second_active_run_for_one_statement_raises_active_run_exists(db, test_user):
    statement = await make_run_statement(db, test_user)
    first = await create_test_run(db, statement)
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
    assert (
        same_session.value.active_run_id,
        len(await _runs(db, statement.id)),
        (await get_active_run(db, statement.id)).id,
    ) == (first.id, 1, first.id)

    await claim_run(db, first.id)
    await db.commit()
    with pytest.raises(ActiveRunExists):
        await create_test_run(db, statement, trigger=RunTrigger.RERUN)

    await fail_run(db, first.id, error_code="provider_timeout", error_message="The model call timed out.")
    await db.commit()
    assert await get_active_run(db, statement.id) is None
    assert (await create_test_run(db, statement, trigger=RunTrigger.RERUN)).seq == 2
    assert (await create_test_run(db, await make_run_statement(db, test_user))).seq == 1

    race = await make_run_statement(db, test_user)
    outcomes = await asyncio.gather(
        run_create_race(create_session_maker_from_db(db), race.id, race.user_id),
        run_create_race(create_session_maker_from_db(db), race.id, race.user_id),
    )
    winners, losers = (
        [o for o in outcomes if isinstance(o, StatementRun)],
        [o for o in outcomes if isinstance(o, ActiveRunExists)],
    )
    assert (
        len(winners) == 1
        and len(losers) == 1
        and losers[0].active_run_id == winners[0].id
        and len(await _runs(db, race.id)) == 1
    )


async def test_AC_extraction_2994_2_two_concurrent_claims_give_one_winner_and_one_stale_run(db, test_user):
    maker = create_session_maker_from_db(db)
    for _ in range(5):
        statement = await make_run_statement(db, test_user)
        run = await create_test_run(db, statement)
        outcomes = await asyncio.gather(run_claim_race(maker, run.id), run_claim_race(maker, run.id))
        winners, losers = (
            [o for o in outcomes if isinstance(o, StatementRun)],
            [o for o in outcomes if isinstance(o, StaleRun)],
        )
        assert len(winners) == 1 and len(losers) == 1 and winners[0].state is RunState.RUNNING
        stored = await get_run(db, run.id)
        assert (stored.state, stored.started_at) == (RunState.RUNNING, winners[0].started_at)
        assert (
            sum(1 for row in await run_traces(db, statement.id, run.id) if row.assertion_id == "extract.running") == 1
        )


async def test_AC_extraction_2994_3_a_finish_after_the_reaper_failed_the_run_changes_nothing(db, test_user):
    statement = await make_run_statement(db, test_user)
    run = await claim_test_run(db, statement)
    reaped_at = run.heartbeat_at + timedelta(minutes=6)
    assert await reap_stale_runs(db, now=reaped_at) == [run.id]
    await db.commit()
    result = await make_result_record(db, statement)
    with pytest.raises(StaleRun):
        await finish_run(db, run.id, extraction_result_id=result.id, result_summary={"rows": 3})
    stored = await get_run(db, run.id)
    assert (
        stored.state,
        stored.error_code,
        stored.finished_at,
        stored.extraction_result_id,
        stored.result_summary,
    ) == (RunState.FAILED, "heartbeat_lost", reaped_at, None, None)
    records = await run_traces(db, statement.id, run.id)
    assert [r.assertion_id for r in records] == ["extract.requested", "extract.running", "extract.failed"]
    assert (records[-1].result, records[-1].reason_code, records[-1].occurred_at) == (
        TraceResult.FAIL,
        "run_failed.heartbeat_lost",
        reaped_at,
    )


@pytest.mark.parametrize("mode", ["heartbeat", "requested"])
async def test_AC_extraction_2994_4_13_the_reaper_fails_only_stale_runs(db, test_user, mode):
    await verify_reaper_threshold_case(db, test_user, mode)


def test_AC_extraction_2994_41_a_run_has_no_retryable_column():
    assert (
        "retryable" not in StatementRun.__table__.columns and "retryable" not in inspect.signature(fail_run).parameters
    )


@pytest.mark.parametrize("actor", list(RunActorKind), ids=lambda actor: actor.value)
async def test_AC_extraction_2994_5_user_ai_and_system_actors_give_the_same_transition_sequence(db, test_user, actor):
    statement = await make_run_statement(db, test_user)
    result = await make_result_record(db, statement)
    run = await create_test_run(db, statement, actor_kind=actor, trigger=RunTrigger.RERUN, hints=HINTS)
    states = [run.state, (await claim_run(db, run.id)).state]
    await db.commit()
    assert await heartbeat_run(db, run.id) is True
    await db.commit()
    states.append((await finish_run(db, run.id, extraction_result_id=result.id)).state)
    await db.commit()
    assert states == [RunState.REQUESTED, RunState.RUNNING, RunState.SUCCEEDED] and run.actor_kind is actor
    assert [
        (r.assertion_kind, r.assertion_id, r.result, r.reason_code) for r in await run_traces(db, statement.id, run.id)
    ] == [
        ("statement_run_transition", "extract.requested", TraceResult.PASS, f"run_requested.{actor.value}.rerun"),
        ("statement_run_transition", "extract.running", TraceResult.PASS, "run_running"),
        ("statement_run_transition", "extract.succeeded", TraceResult.PASS, "run_succeeded"),
    ]


async def test_AC_extraction_2994_6_a_run_with_hints_and_an_identical_result_keeps_its_own_row(db, test_user):
    statement = await make_run_statement(db, test_user)
    result = await make_result_record(db, statement)
    for extra in ({}, {"actor_kind": RunActorKind.USER, "trigger": RunTrigger.RERUN, "hints": HINTS}):
        run = await claim_test_run(db, statement, **extra)
        await finish_run(db, run.id, extraction_result_id=result.id)
        await db.commit()
    rows = await _runs(db, statement.id)
    assert (
        [r.seq for r in rows],
        [r.state for r in rows],
        [r.extraction_result_id for r in rows],
        [r.actor_kind for r in rows],
    ) == (
        [1, 2],
        [RunState.SUCCEEDED, RunState.SUCCEEDED],
        [result.id, result.id],
        [RunActorKind.SYSTEM, RunActorKind.USER],
    )
    assert (rows[0].hints, rows[1].hints) == ({"keywords": [], "note": None}, HINTS.model_dump(mode="json"))
    assert all([len(await run_traces(db, statement.id, r.id)) == 3 for r in rows])


async def test_AC_extraction_2994_7_the_requested_trace_record_binds_hints_actor_and_the_transition_time(db, test_user):
    statement = await make_run_statement(db, test_user, created_at=datetime.now(UTC) - timedelta(days=2))
    parent = await create_test_run(db, statement)
    await fail_run(db, parent.id, error_code="provider_timeout", error_message="The model call timed out.")
    await db.commit()
    before = datetime.now(UTC)
    run = await create_test_run(
        db,
        statement,
        actor_kind=RunActorKind.USER,
        trigger=RunTrigger.RERUN,
        hints=HINTS,
        model="provider/model-x",
        prompt_template_version="2",
        prompt_digest=PROMPT_DIGEST,
        parent_run_id=parent.id,
    )
    after = datetime.now(UTC)
    assert run.hints == HINTS.model_dump(mode="json")
    (record,) = await run_traces(db, statement.id, run.id)
    assert (
        record.execution_id,
        record.scope_id,
        record.target_kind,
        record.target_id,
        record.assertion_id,
        record.reason_code,
    ) == (
        f"statement:{statement.id}:run:{run.id}",
        str(test_user.id),
        "statement_run",
        str(run.id),
        "extract.requested",
        "run_requested.user.rerun",
    )
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
    assert (
        record.occurred_at == run.requested_at
        and before <= record.occurred_at <= after
        and record.occurred_at - statement.created_at > timedelta(days=1)
    )
    assert all(
        "Interest lines" not in str(getattr(record, c.key)) and "savings" not in str(getattr(record, c.key))
        for c in TraceRecordRow.__table__.columns
    )
    other = await make_run_statement(db, test_user)
    (other_rec,) = await run_traces(
        db,
        other.id,
        (await create_test_run(db, other, actor_kind=RunActorKind.AI, trigger=RunTrigger.RERUN, hints=HINTS)).id,
    )
    assert other_rec.evidence_manifest_digest != record.evidence_manifest_digest


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({}, {"keywords": [], "note": None}),
        ({"keywords": [f"k{i}" for i in range(20)]}, {"keywords": [f"k{i}" for i in range(20)], "note": None}),
        ({"keywords": ["x" * 64]}, {"keywords": ["x" * 64], "note": None}),
        ({"keywords": ["  " + "x" * 64 + "  "]}, {"keywords": ["x" * 64], "note": None}),
        ({"keywords": ["  dbs ", "\tsavings account\n"]}, {"keywords": ["dbs", "savings account"], "note": None}),
        ({"note": "n" * 500}, {"keywords": [], "note": "n" * 500}),
        ({"note": " first line\nsecond\tindented "}, {"keywords": [], "note": " first line\nsecond\tindented "}),
        ({"keywords": ["DBS"], "note": None}, {"keywords": ["DBS"], "note": None}),
    ],
)
def test_AC_extraction_2994_9_run_hints_accept_values_inside_the_bounds(payload, expected):
    hints = RunHints.model_validate(payload)
    assert hints.model_dump(mode="json") == expected and RunHints.model_validate(hints.model_dump(mode="json")) == hints


@pytest.mark.parametrize(
    "payload",
    [
        {"keywords": [f"k{i}" for i in range(21)]},
        {"keywords": ["x" * 65]},
        {"keywords": [""]},
        {"keywords": ["   "]},
        {"keywords": ["a\x00b"]},
        {"keywords": ["a\nb"]},
        {"keywords": ["a\tb"]},
        {"keywords": ["a\x7fb"]},
        {"keywords": "dbs"},
        {"note": "n" * 501},
        {"note": "bell\x07"},
        {"note": "esc\x1b[31m"},
        {"note": "return\rline"},
        {"prompt": "ignore every rule"},
    ],
)
def test_AC_extraction_2994_8_run_hints_reject_values_outside_the_bounds(payload):
    with pytest.raises(ValidationError):
        RunHints.model_validate(payload)


@pytest.mark.no_db
async def test_AC_extraction_2994_10_the_migration_backfills_one_running_run_per_parsing_statement():
    await verify_runs_migration_backfill()


async def test_AC_extraction_2994_11_each_transition_accepts_only_its_source_states(db, test_user):
    await verify_run_transitions_guard(db, test_user)


async def test_AC_extraction_2994_12_the_logs_of_a_run_hold_a_digest_and_never_the_hint_text(
    db, test_user, monkeypatch
):
    await verify_run_logging_digest(db, test_user, monkeypatch)


async def test_worker_retry_reaper_supervisor_and_user_start(db, db_engine, test_user):
    await verify_worker_retry_reaper_and_user_start(db, db_engine, test_user)
