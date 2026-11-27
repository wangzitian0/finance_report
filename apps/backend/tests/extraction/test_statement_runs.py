"""Statement run record and its state module (#2994, phase A)."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text

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
    BACKEND_DIR,
    _runs,
    claim_test_run,
    create_test_run,
    get_run,
    make_result_record,
    make_run_statement,
    migration_db_url,
    run_alembic,
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


async def test_AC_extraction_2994_1_active_run_and_create_race(db, test_user):
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
    assert (
        await get_active_run(db, statement.id),
        (await create_test_run(db, statement, trigger=RunTrigger.RERUN)).seq,
        (await create_test_run(db, await make_run_statement(db, test_user))).seq,
    ) == (None, 2, 1)

    race, maker = await make_run_statement(db, test_user), create_session_maker_from_db(db)
    outcomes = await asyncio.gather(
        run_create_race(maker, race.id, race.user_id), run_create_race(maker, race.id, race.user_id)
    )
    winners, losers = (
        [o for o in outcomes if isinstance(o, StatementRun)],
        [o for o in outcomes if isinstance(o, ActiveRunExists)],
    )
    assert (
        len(winners) == len(losers) == 1
        and losers[0].active_run_id == winners[0].id
        and len(await _runs(db, race.id)) == 1
    )


async def test_AC_extraction_2994_2_3_41_claim_race_and_finish_after_reaper(db, test_user):
    maker, race_ids = create_session_maker_from_db(db), set()
    for _ in range(5):
        statement = await make_run_statement(db, test_user)
        run = await create_test_run(db, statement)
        race_ids.add(run.id)
        outcomes = await asyncio.gather(run_claim_race(maker, run.id), run_claim_race(maker, run.id))
        winners, losers = (
            [o for o in outcomes if isinstance(o, StatementRun)],
            [o for o in outcomes if isinstance(o, StaleRun)],
        )
        stored = await get_run(db, run.id)
        assert (
            len(winners) == len(losers) == 1
            and (winners[0].state, stored.state, stored.started_at)
            == (RunState.RUNNING, RunState.RUNNING, winners[0].started_at)
            and sum(1 for row in await run_traces(db, statement.id, run.id) if row.assertion_id == "extract.running")
            == 1
        )

    assert (
        "retryable" not in StatementRun.__table__.columns and "retryable" not in inspect.signature(fail_run).parameters
    )
    stmt2 = await make_run_statement(db, test_user)
    run2 = await claim_test_run(db, stmt2)
    reaped_at = run2.heartbeat_at + timedelta(minutes=6)
    assert set(await reap_stale_runs(db, now=reaped_at)) == race_ids | {run2.id}
    await db.commit()
    result = await make_result_record(db, stmt2)
    with pytest.raises(StaleRun):
        await finish_run(db, run2.id, extraction_result_id=result.id, result_summary={"rows": 3})
    stored2, records = await get_run(db, run2.id), await run_traces(db, stmt2.id, run2.id)
    assert (
        stored2.state,
        stored2.error_code,
        stored2.finished_at,
        stored2.extraction_result_id,
        stored2.result_summary,
        [r.assertion_id for r in records],
        records[-1].result,
        records[-1].reason_code,
        records[-1].occurred_at,
    ) == (
        RunState.FAILED,
        "heartbeat_lost",
        reaped_at,
        None,
        None,
        ["extract.requested", "extract.running", "extract.failed"],
        TraceResult.FAIL,
        "run_failed.heartbeat_lost",
        reaped_at,
    )


@pytest.mark.parametrize("actor", list(RunActorKind), ids=lambda actor: actor.value)
async def test_AC_extraction_2994_5_user_ai_and_system_actors_give_the_same_transition_sequence(db, test_user, actor):
    statement = await make_run_statement(db, test_user)
    result, run = (
        await make_result_record(db, statement),
        await create_test_run(db, statement, actor_kind=actor, trigger=RunTrigger.RERUN, hints=HINTS),
    )
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


async def test_AC_extraction_2994_6_7_hints_row_isolation_and_requested_trace_record(db, test_user):
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
        rows[0].hints,
        rows[1].hints,
    ) == (
        [1, 2],
        [RunState.SUCCEEDED, RunState.SUCCEEDED],
        [result.id, result.id],
        [RunActorKind.SYSTEM, RunActorKind.USER],
        {"keywords": [], "note": None},
        HINTS.model_dump(mode="json"),
    )
    assert all([len(await run_traces(db, statement.id, r.id)) == 3 for r in rows])

    s2 = await make_run_statement(db, test_user, created_at=datetime.now(UTC) - timedelta(days=2))
    parent = await create_test_run(db, s2)
    await fail_run(db, parent.id, error_code="provider_timeout", error_message="The model call timed out.")
    await db.commit()
    before = datetime.now(UTC)
    run2 = await create_test_run(
        db,
        s2,
        actor_kind=RunActorKind.USER,
        trigger=RunTrigger.RERUN,
        hints=HINTS,
        model="provider/model-x",
        prompt_template_version="2",
        prompt_digest=PROMPT_DIGEST,
        parent_run_id=parent.id,
    )
    after = datetime.now(UTC)
    (record,) = await run_traces(db, s2.id, run2.id)
    expected_digest = canonical_json_digest(
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
        run2.hints,
        record.execution_id,
        record.scope_id,
        record.target_kind,
        record.target_id,
        record.assertion_id,
        record.reason_code,
        record.evidence_manifest_digest,
        record.occurred_at,
    ) == (
        HINTS.model_dump(mode="json"),
        f"statement:{s2.id}:run:{run2.id}",
        str(test_user.id),
        "statement_run",
        str(run2.id),
        "extract.requested",
        "run_requested.user.rerun",
        expected_digest,
        run2.requested_at,
    )
    assert (
        before <= record.occurred_at <= after
        and record.occurred_at - s2.created_at > timedelta(days=1)
        and all(
            "Interest lines" not in str(getattr(record, c.key)) and "savings" not in str(getattr(record, c.key))
            for c in TraceRecordRow.__table__.columns
        )
    )
    other = await make_run_statement(db, test_user)
    (other_rec,) = await run_traces(
        db,
        other.id,
        (await create_test_run(db, other, actor_kind=RunActorKind.AI, trigger=RunTrigger.RERUN, hints=HINTS)).id,
    )
    assert other_rec.evidence_manifest_digest != record.evidence_manifest_digest


@pytest.mark.no_db
def test_AC_extraction_2994_8_9_run_hints_validation_bounds():
    valid = [
        ({}, {"keywords": [], "note": None}),
        ({"keywords": [f"k{i}" for i in range(20)]}, {"keywords": [f"k{i}" for i in range(20)], "note": None}),
        ({"keywords": ["x" * 64]}, {"keywords": ["x" * 64], "note": None}),
        ({"keywords": ["  " + "x" * 64 + "  "]}, {"keywords": ["x" * 64], "note": None}),
        ({"keywords": ["  dbs ", "\tsavings account\n"]}, {"keywords": ["dbs", "savings account"], "note": None}),
        ({"note": "n" * 500}, {"keywords": [], "note": "n" * 500}),
        ({"note": " first line\nsecond\tindented "}, {"keywords": [], "note": " first line\nsecond\tindented "}),
        ({"keywords": ["DBS"], "note": None}, {"keywords": ["DBS"], "note": None}),
    ]
    for payload, expected in valid:
        hints = RunHints.model_validate(payload)
        assert (
            hints.model_dump(mode="json") == expected
            and RunHints.model_validate(hints.model_dump(mode="json")) == hints
        )
    invalid = [
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
    ]
    for payload in invalid:
        with pytest.raises(ValidationError):
            RunHints.model_validate(payload)


async def test_AC_extraction_2994_10_the_migration_backfills_one_running_run_per_parsing_statement():
    await verify_runs_migration_backfill()


@pytest.mark.parametrize("mode", ["heartbeat", "requested", "transitions", "logging_digest", "worker_retry"])
async def test_AC_extraction_2994_delegated_run_checks(db, db_engine, test_user, monkeypatch, mode):
    if mode in ("heartbeat", "requested"):
        await verify_reaper_threshold_case(db, test_user, mode)
    elif mode == "transitions":
        await verify_run_transitions_guard(db, test_user)
    elif mode == "logging_digest":
        await verify_run_logging_digest(db, test_user, monkeypatch)
    else:
        await verify_worker_retry_reaper_and_user_start(db, db_engine, test_user)


def test_AC_extraction_2983_migration_sub_account_key_upgrade_and_downgrade():
    """#2983: 0077_stmt_summary_sub_account widens uniqueness, matches ORM via alembic check, and guards downgrade."""
    name = f"fr_ac_2983_sub_{uuid4().hex[:12]}"
    admin = create_engine(migration_db_url("postgres").replace("+asyncpg", ""), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    database_url = migration_db_url(name)
    engine = create_engine(database_url.replace("+asyncpg", ""))
    user_id = uuid4()
    shared_hash = hashlib.sha256(b"multi-account").hexdigest()
    try:
        run_alembic(database_url, "upgrade", "0076_txn_classif_live_unique")
        run_alembic(database_url, "upgrade", "0077_stmt_summary_sub_account")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password, ai_settings, created_at, updated_at) "
                    "VALUES (:id, :email, 'generated-hash', CAST('{}' AS jsonb), NOW(), NOW())"
                ),
                {"id": user_id, "email": f"subacct-{user_id.hex}@example.test"},
            )
            for sub_key in ["", "5678:EUR"]:
                connection.execute(
                    text(
                        "INSERT INTO statement_summaries "
                        "(id, user_id, file_hash, sub_account_key, institution, status, created_at, updated_at) "
                        "VALUES (:id, :user_id, :file_hash, :sub_key, 'BNP', 'parsed', NOW(), NOW())"
                    ),
                    {"id": uuid4(), "user_id": user_id, "file_hash": shared_hash, "sub_key": sub_key},
                )
        downgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "0076_txn_classif_live_unique"],
            cwd=BACKEND_DIR,
            env={**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "testing"},
            check=False,
            capture_output=True,
            text=True,
        )
        assert downgrade.returncode != 0 and "sub-account summaries" in (downgrade.stdout + downgrade.stderr)
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM statement_summaries WHERE sub_account_key <> ''"))
        run_alembic(database_url, "downgrade", "0076_txn_classif_live_unique")
        run_alembic(database_url, "upgrade", "0077_stmt_summary_sub_account")
        run_alembic(database_url, "upgrade", "head")
        run_alembic(database_url, "check")
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.mark.no_db
def test_issue_codes_contract_and_redacted_diagnostics_snapshot() -> None:
    """L3/L4 pure contract: typed enums, lowercase error codes, and PII-free diagnostics."""
    import re
    from decimal import Decimal

    from src.extraction.base.issue_codes import (
        RunFailureCode,
        StatementIssueCode,
        build_redacted_diagnostics,
        classify_run_failure_code,
        classify_statement_issue_codes,
    )

    for code in RunFailureCode:
        assert re.fullmatch(r"^[a-z][a-z0-9_]{0,63}$", code.value), code

    assert (
        classify_run_failure_code(error_type="TimeoutError", message="wall_clock timeout")
        is RunFailureCode.PARSE_WALL_CLOCK_TIMEOUT
    )
    assert classify_run_failure_code(error_type="TimeoutError", message="timed out") is RunFailureCode.PROVIDER_TIMEOUT
    assert (
        classify_run_failure_code(
            error_type="ExtractionError",
            message="Extraction failed (rate_limit): Model rate limited",
        )
        is RunFailureCode.PROVIDER_RATE_LIMITED
    )
    assert (
        classify_run_failure_code(
            error_type="ExtractionError",
            message="Extraction failed (json_parse): invalid JSON",
        )
        is RunFailureCode.INVALID_JSON_PAYLOAD
    )

    codes = classify_statement_issue_codes(
        missing_facts=["institution", "transaction_currency", "balances"],
        balance_validated=False,
        has_account=False,
        validation_error="Economic review required: intent_missing; Closing balance 100.00 is not in the document text",
        rows_not_in_text=[2, 5],
        closing_not_in_text=True,
    )
    assert StatementIssueCode.MISSING_INSTITUTION in codes
    assert StatementIssueCode.MISSING_TRANSACTION_CURRENCY in codes
    assert StatementIssueCode.MISSING_BALANCES in codes
    assert StatementIssueCode.BALANCE_CHAIN_MISMATCH in codes
    assert StatementIssueCode.CUSTODY_ACCOUNT_REQUIRED in codes
    assert StatementIssueCode.ECONOMIC_DISPOSITION_REQUIRED in codes
    assert StatementIssueCode.CLOSING_NOT_IN_SOURCE_TEXT in codes
    assert StatementIssueCode.ROWS_NOT_IN_TEXT in codes

    diag = build_redacted_diagnostics(
        modality="pdf_text",
        page_count=6,
        batch_count=2,
        pass_durations_ms=[1240, 810],
        expected_closing=Decimal("15271.23"),
        calculated_closing=Decimal("15000.00"),
        balance_gap=Decimal("271.23"),
        suspect_row_indices=[3, 7],
        rows_not_in_text_indices=[7],
        issue_codes=codes,
        failure_code=None,
    )
    assert diag["modality"] == "pdf_text"
    assert diag["page_count"] == 6 and diag["batch_count"] == 2
    assert diag["pass_durations_ms"] == [1240, 810]
    assert diag["balance_gap"] == "271.23"
    assert diag["suspect_row_indices"] == [3, 7]
    assert diag["rows_not_in_text_indices"] == [7]


async def test_statement_run_record_exposes_persisted_diagnostics(db, test_user) -> None:
    """StatementRunRecord reads redacted result_summary['diagnostics'] without leaking PII into TraceRecord."""
    from src.extraction import list_runs
    from src.extraction.base.issue_codes import RunFailureCode, StatementIssueCode, build_redacted_diagnostics

    statement = await make_run_statement(db, test_user)
    diag = build_redacted_diagnostics(
        modality="pdf_vision",
        page_count=4,
        batch_count=1,
        pass_durations_ms=[2100],
        balance_gap=None,
        suspect_row_indices=[],
        rows_not_in_text_indices=[],
        issue_codes=[StatementIssueCode.UNVERIFIABLE_TEXT_LAYER],
        failure_code=RunFailureCode.PROVIDER_RATE_LIMITED,
    )
    run = await claim_test_run(db, statement)
    await fail_run(
        db,
        run.id,
        error_code=RunFailureCode.PROVIDER_RATE_LIMITED.value,
        error_message="Provider rate limited.",
        result_summary={"diagnostics": diag},
    )
    await db.commit()

    records = await list_runs(db, statement.id, test_user.id)
    assert len(records) == 1
    assert records[0].diagnostics is not None
    assert records[0].diagnostics.modality == "pdf_vision"
    assert records[0].diagnostics.failure_code == "provider_rate_limited"
    assert records[0].error_code == "provider_rate_limited"
