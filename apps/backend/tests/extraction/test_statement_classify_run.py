"""Classification is a run with a state; the approve only posts (#2994, slice S3)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.audit.orm import TraceRecordRow
from src.composition import auto_fill_default_statement_dispositions, compose_statement_posting_dependencies
from src.config import settings
from src.database import create_session_maker_from_db
from src.extraction import (
    ActiveRunExists,
    BankStatementStatus,
    ExtractionError,
    RuleType,
    RunActorKind,
    RunKind,
    RunState,
    RunTrigger,
    StatementIngestionStatus,
)
from src.extraction.extension import statement_parsing, transaction_classification
from src.extraction.extension.statement_posting import auto_approve_parsed_candidate
from src.extraction.extension.transaction_classification import (
    CLASSIFICATION_PHASE_DEADLINE_SECONDS,
    ClassificationOutcome,
    summarize_outcomes,
)
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.ledger import Account, JournalEntry
from src.schemas.extraction import StatementReviewResponse
from tests.extraction._statement_run_helpers import (
    ANSWERS,
    CSV,
    WAIT_SECONDS,
    Proposer,
    ScriptedService,
    Sleeps,
    _count,
    _runs,
    _statement,
    _statement_with_run,
    _use_case,
    _worker,
    add_coffee_rule as _add_coffee_rule,
    count_user_answers as _answers,
    create_parsing_job as _parsing_job,
    get_run as _run,
    high_confidence_pdf_service as _high_confidence,
    install_proposer as _install,
    make_rows as _rows,
    parsed_candidate_after_extract as _parsed_candidate_after_an_extract_run,
    seed_classify_statement as _seed,
    spy_classify_outcomes as _spy_outcomes,
    verify_approve_active_or_failed_classify_run,
    verify_classify_reaper_paths,
    verify_gated_auto_approve,
    verify_phase_batches_release_connections,
    verify_two_writers_keyword_rule_serialize,
)
from tests.factories import seed_parsed_statement
from tests.statement_ingestion import classify_run_for, classify_statement

DEADLINE_SECONDS = 3.0


@pytest.fixture(autouse=True)
def _model_on(monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", True)
    monkeypatch.setattr(settings, "ai_api_key", "test-key")


async def test_AC_extraction_2994_88_a_successful_extract_run_creates_the_classify_run_in_its_transaction(
    db, test_user, monkeypatch
):
    statement_id, job = await _statement_with_run(db, test_user)
    received: list = []
    monkeypatch.setattr(
        statement_parsing,
        "execute_classify_run",
        AsyncMock(side_effect=lambda _sm, *, run_id, **_kw: received.append(run_id) or 0),
    )
    outcome = await _use_case(db).execute(job, content=CSV)
    extract, classify = await _runs(db, statement_id)
    assert (outcome.status, extract.kind, extract.state) == (
        StatementIngestionStatus.COMPLETED,
        RunKind.EXTRACT,
        RunState.SUCCEEDED,
    )
    assert (
        classify.kind,
        classify.state,
        classify.seq,
        classify.actor_kind,
        classify.trigger,
        classify.parent_run_id,
        classify.hints,
        classify.model,
    ) == (
        RunKind.CLASSIFY,
        RunState.REQUESTED,
        2,
        RunActorKind.SYSTEM,
        RunTrigger.AUTO_CLASSIFY,
        extract.id,
        {"keywords": [], "note": None},
        None,
    )
    assert received == [classify.id] and (await _statement(db, statement_id)).status is BankStatementStatus.PARSED


async def test_AC_extraction_2994_88_89_extract_failure_and_classify_insert_atomicity(db, test_user, monkeypatch):
    statement_id, job = await _statement_with_run(db, test_user)
    real_create_run = statement_parsing.create_run
    monkeypatch.setattr(
        statement_parsing,
        "create_run",
        lambda s, **kw: (_ for _ in ()).throw(RuntimeError("the classify run insert failed"))
        if kw["kind"] is RunKind.CLASSIFY
        else real_create_run(s, **kw),
    )
    with pytest.raises(Exception, match="finalization"):
        await _use_case(db, sleeps=Sleeps()).execute(job, content=CSV)
    runs = await _runs(db, statement_id)
    assert (
        {r.kind for r in runs} == {RunKind.EXTRACT}
        and RunState.SUCCEEDED not in {r.state for r in runs}
        and (await _statement(db, statement_id)).status is BankStatementStatus.PARSING
    )

    sid_fail, job_fail = await _statement_with_run(db, test_user)
    spy = AsyncMock(return_value=0)
    monkeypatch.setattr(statement_parsing, "execute_classify_run", spy)
    assert (
        await _use_case(db, ScriptedService([ExtractionError("unreadable")])).execute(job_fail, content=CSV)
    ).status is StatementIngestionStatus.SOURCE_REJECTED
    assert [(r.kind, r.state) for r in await _runs(db, sid_fail)] == [(RunKind.EXTRACT, RunState.FAILED)]
    spy.assert_not_awaited()


async def test_AC_extraction_2994_90_a_classify_run_ends_with_counts_and_no_row_text(db, test_user, monkeypatch):
    outcomes, proposer, seeded = (
        _spy_outcomes(monkeypatch),
        _install(monkeypatch, Proposer()),
        await _seed(db, test_user),
    )
    run_id = await classify_statement(db, seeded.id)
    run = await _run(db, run_id)
    assert (
        (run.kind, run.state, run.error_code) == (RunKind.CLASSIFY, RunState.SUCCEEDED, None)
        and run.started_at
        and run.heartbeat_at
        and run.finished_at
    )
    assert (
        run.result_summary["outcome"],
        run.result_summary["total"],
        run.result_summary["by_disposition"],
        run.result_summary["by_category"]["SALARY"],
    ) == ("classified", 5, {"applied": 5}, 1)
    flat = json.dumps(run.result_summary)
    assert all(row["description"] not in flat and str(row["amount"]) not in flat for row in _rows())
    assert (proposer.rows_asked, await _answers(db, test_user), outcomes) == (5, 5, ["classified"])
    assert list(
        (
            await db.execute(
                select(TraceRecordRow.assertion_id)
                .where(TraceRecordRow.execution_id == f"statement:{seeded.id}:run:{run_id}")
                .order_by(TraceRecordRow.occurred_at)
            )
        ).scalars()
    ) == ["classify.requested", "classify.running", "classify.succeeded"]


async def test_AC_extraction_2994_91_a_classify_run_that_passes_its_deadline_fails_with_a_timeout_code(
    db, test_user, monkeypatch
):
    outcomes, hung, seeded = (
        _spy_outcomes(monkeypatch),
        _install(monkeypatch, Proposer(gate=asyncio.Event())),
        await _seed(db, test_user),
    )
    run_id = await classify_run_for(db, seeded.id)
    posted = await asyncio.wait_for(
        _worker(create_session_maker_from_db(db), run_id, deadline_seconds=DEADLINE_SECONDS), timeout=WAIT_SECONDS
    )
    run = await _run(db, run_id)
    assert (posted, run.state, run.error_code, hung.rows_asked, await _answers(db, test_user), outcomes) == (
        0,
        RunState.FAILED,
        "classification_timeout",
        5,
        0,
        ["timed_out"],
    )
    assert (await _statement(db, seeded.id)).status is BankStatementStatus.PARSED


@pytest.mark.parametrize(
    "error", [RuntimeError("secret Salary 000 owner@example.com 2500.00"), TimeoutError("connect")]
)
async def test_AC_extraction_2994_92_any_other_error_fails_the_run_with_a_code_and_no_row_text(
    db, test_user, monkeypatch, error
):
    outcomes, _ = _spy_outcomes(monkeypatch), _install(monkeypatch, Proposer(error=error))
    seeded = await _seed(db, test_user)
    run = await _run(db, await classify_statement(db, seeded.id))
    assert (run.state, run.error_code, await _answers(db, test_user), outcomes) == (
        RunState.FAILED,
        "classification_failed",
        0,
        ["failed"],
    )
    assert (
        run.error_message
        and len(run.error_message) <= 500
        and all(s not in run.error_message for s in ("Salary", "owner@example.com", "2500.00"))
    )
    assert (await _statement(db, seeded.id)).status is BankStatementStatus.PARSED


@pytest.mark.parametrize("mode", ["disabled", "refused", "empty", "retired"])
async def test_AC_extraction_2994_93_94_classify_run_outcomes_without_full_classification(
    db, test_user, monkeypatch, mode
):
    outcomes = _spy_outcomes(monkeypatch)
    if mode == "disabled":
        monkeypatch.setattr(settings, "enable_ai_classification", False)
    proposer = _install(
        monkeypatch,
        Proposer(
            error=AssertionError("asked") if mode == "disabled" else None,
            refuse=frozenset({"Coffee"}) if mode == "refused" else frozenset(),
        ),
    )
    seeded = (
        await seed_parsed_statement(db, test_user.id, original_filename="empty.pdf", transactions=[])
        if mode == "empty"
        else await _seed(db, test_user)
    )
    if mode == "retired":
        seeded.statement.status = BankStatementStatus.RETIRED
        await db.commit()
    run = await _run(db, await classify_statement(db, seeded.id))
    expected = {
        "disabled": "skipped_disabled",
        "refused": "partial",
        "empty": "nothing_to_classify",
        "retired": "skipped_state",
    }[mode]
    assert (run.state, run.result_summary["outcome"], outcomes) == (RunState.SUCCEEDED, expected, [expected])
    assert mode == "refused" or proposer.calls == []


async def test_AC_extraction_2994_95_reaper_fails_unclaimed_and_lost_heartbeat_runs(db, test_user, monkeypatch):
    await verify_classify_reaper_paths(db, test_user, monkeypatch)


async def test_AC_extraction_2994_97_the_classify_run_answers_a_keyword_rule_row_without_the_model_and_approve_posts(
    client, db, test_user, monkeypatch
):
    proposer, seeded = _install(monkeypatch, Proposer()), await _seed(db, test_user)
    await _add_coffee_rule(db, test_user)
    run_id = await classify_statement(db, seeded.id)
    assert (
        (await _run(db, run_id)).state is RunState.SUCCEEDED
        and proposer.rows_asked == 4
        and not any(d.startswith("Coffee") for c in proposer.calls for d in c)
    )
    assert (
        await _count(
            db,
            TransactionClassification,
            TransactionClassification.rule_version_id.in_(
                select(ClassificationRule.id).where(ClassificationRule.rule_type == RuleType.KEYWORD_MATCH)
            ),
        )
        == 1
    )
    resp = await client.post(f"/statements/{seeded.id}/approvals", json={"create_account_if_missing": True})
    assert (resp.status_code, resp.json()["journal_entries_created"], proposer.rows_asked) == (200, 5, 4)


async def test_AC_extraction_2994_98_approve_with_active_or_failed_classify_run(client, db, test_user, monkeypatch):
    await verify_approve_active_or_failed_classify_run(client, db, test_user, monkeypatch)


async def test_AC_extraction_2994_99_a_high_confidence_statement_is_approved_only_after_the_classify_run_succeeded(
    client, db, test_user, monkeypatch
):
    await verify_gated_auto_approve(client, db, test_user, monkeypatch)


async def test_AC_extraction_2994_99_high_and_low_confidence_non_auto_approve_paths(db, test_user, monkeypatch):
    _install(monkeypatch, Proposer(error=RuntimeError("provider down")))
    service, content = _high_confidence(_rows())
    sid, job = await _parsing_job(db, test_user, content)
    outcome = await _use_case(db, service).execute(job, content=content)
    stmt = await _statement(db, sid)
    assert (outcome.status, outcome.auto_posted_count, stmt.status, stmt.validation_error) == (
        StatementIngestionStatus.COMPLETED,
        0,
        BankStatementStatus.PARSED,
        None,
    )
    assert [(r.kind, r.state) for r in await _runs(db, sid)] == [
        (RunKind.EXTRACT, RunState.SUCCEEDED),
        (RunKind.CLASSIFY, RunState.FAILED),
    ]

    _install(monkeypatch, Proposer())
    low_id, low_job = await _statement_with_run(db, test_user)
    low_out = await _use_case(db).execute(low_job, content=CSV)
    extract, classify = await _runs(db, low_id)
    assert (
        extract.result_summary,
        classify.state,
        low_out.auto_posted_count,
        (await _statement(db, low_id)).status,
        await _count(db, JournalEntry),
    ) == ({"auto_approve_candidate": False}, RunState.SUCCEEDED, 0, BankStatementStatus.PARSED, 0)


@pytest.mark.parametrize(
    ("marked", "expected_posted", "expected_status"),
    [(False, 0, BankStatementStatus.PARSED), (True, 5, BankStatementStatus.APPROVED)],
)
async def test_AC_extraction_2994_99_the_mark_of_the_parse_decides_auto_approve(
    db, test_user, monkeypatch, marked, expected_posted, expected_status
):
    _install(monkeypatch, Proposer())
    statement_id, run_id = await _parsed_candidate_after_an_extract_run(db, test_user, marked=marked)
    posted = await _worker(create_session_maker_from_db(db), run_id)
    assert ((await _run(db, run_id)).state, posted, (await _statement(db, statement_id)).status) == (
        RunState.SUCCEEDED,
        expected_posted,
        expected_status,
    )
    assert await _count(db, JournalEntry) >= 5 if marked else await _count(db, JournalEntry) == 0


async def test_AC_extraction_2994_99_the_auto_approve_leaves_a_statement_that_a_user_approved_first(
    client, db, test_user, monkeypatch
):
    _install(monkeypatch, Proposer())
    statement_id, run_id = await _parsed_candidate_after_an_extract_run(db, test_user, marked=False)
    maker = create_session_maker_from_db(db)
    await _worker(maker, run_id)
    assert (await client.post(f"/statements/{statement_id}/approvals", json={})).status_code == 200
    approved = await _statement(db, statement_id)
    reviewed_at, entries = approved.stage1_reviewed_at, await _count(db, JournalEntry)
    async with maker() as session:
        posted = await auto_approve_parsed_candidate(
            session, statement_id, test_user.id, dependencies=compose_statement_posting_dependencies()
        )
        await session.commit()
    assert (
        posted,
        approved.status,
        (await _statement(db, statement_id)).stage1_reviewed_at,
        await _count(db, JournalEntry),
    ) == (0, BankStatementStatus.APPROVED, reviewed_at, entries)


@pytest.mark.parametrize("model_off", [False, True])
async def test_AC_extraction_2994_99_candidate_without_full_answers_goes_to_economic_review(
    client, db, test_user, monkeypatch, model_off
):
    if model_off:
        monkeypatch.setattr(settings, "enable_ai_classification", False)
    else:
        _install(monkeypatch, Proposer(refuse=frozenset({"Refund"})))
    rows = _rows()
    service, content = _high_confidence(rows)
    sid, job = await _parsing_job(db, test_user, content)
    outcome = await _use_case(db, service).execute(job, content=content)
    stmt = await _statement(db, sid)
    assert (outcome.auto_posted_count, stmt.status, await _count(db, JournalEntry)) == (
        0,
        BankStatementStatus.PARSED,
        0,
    ) and (stmt.validation_error or "").startswith("Economic review required:")
    if not model_off:
        healthy = _install(monkeypatch, Proposer())
        await classify_statement(db, sid)
        resp = await client.post(f"/statements/{sid}/approvals", json={})
        assert (healthy.rows_asked, resp.status_code, resp.json()["journal_entries_created"]) == (1, 200, len(rows))


async def test_AC_extraction_2994_101_155_one_click_fill_guards_and_posts(client, db, test_user, monkeypatch):
    proposer, seeded_active = _install(monkeypatch, Proposer()), await _seed(db, test_user)
    run_id = await classify_run_for(db, seeded_active.id)
    with pytest.raises(ActiveRunExists) as caught:
        await auto_fill_default_statement_dispositions(db, seeded_active.statement, test_user.id)
    assert caught.value.active_run_id == run_id and proposer.calls == []
    resp = await client.post(
        f"/statements/{seeded_active.id}/approvals",
        json={"create_account_if_missing": True, "auto_fill_default_categories": True},
    )
    assert resp.status_code == 409 and resp.json()["active_run_id"] == str(run_id) and proposer.calls == []

    no_model, seeded_fill = (
        _install(monkeypatch, Proposer(error=AssertionError("the fill asked the model"))),
        await _seed(db, test_user),
    )
    filled = await auto_fill_default_statement_dispositions(db, seeded_fill.statement, test_user.id)
    names = set(await db.scalars(select(Account.name).where(Account.user_id == test_user.id)))
    assert (no_model.calls, filled, await _answers(db, test_user)) == ([], 5, 0) and {
        "General Expense (SGD)",
        "General Income (SGD)",
    } <= names


def test_AC_extraction_2994_103_104_and_summarize_outcomes(openapi_schema):
    import src.extraction as package

    assert (
        "preclassification_in_progress" not in StatementReviewResponse.model_fields
        and "preclassification_in_progress"
        not in openapi_schema["components"]["schemas"]["StatementReviewResponse"]["properties"]
    )
    for name in (
        "lock_statement_classification",
        "try_lock_statement_classification",
        "is_statement_classification_running",
        "classify_statement_by_effective_policy",
        "StatementClassificationBusy",
    ):
        assert not hasattr(package, name) and not hasattr(transaction_classification, name)
    for name in ("CLASSIFICATION_LOCK_WAIT_SECONDS", "_LOCK_POLL_SECONDS", "_statement_lock_key"):
        assert not hasattr(transaction_classification, name)
    assert 0 < CLASSIFICATION_PHASE_DEADLINE_SECONDS <= 180
    outcomes = [
        ClassificationOutcome(
            atomic_txn_id=uuid4(), disposition="off_catalog", category="CUSTOM", confidence=90, policy_version=1
        ),
        ClassificationOutcome(
            atomic_txn_id=uuid4(), disposition="applied", category="SALARY", confidence=95, policy_version=1
        ),
    ]
    assert summarize_outcomes(outcomes)["by_category"] == {"other": 1, "SALARY": 1}


async def test_phase_batches_commit_independently_and_release_connections(
    db, test_user, test_database_url, monkeypatch
):
    await verify_phase_batches_release_connections(db, test_user, test_database_url, monkeypatch)


async def test_two_writers_of_keyword_rule_serialize_without_collision(db, test_user):
    await verify_two_writers_keyword_rule_serialize(db, test_user)
