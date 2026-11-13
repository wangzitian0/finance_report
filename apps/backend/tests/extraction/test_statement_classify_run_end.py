"""The end of a classify run (#2994, slice S3 review).

A candidate that the parse marked keeps its run active until the auto-approve ends it, in one transaction: no
moment shows PARSED without an active run. No row text and no driver detail reaches a run summary, an error message
or a log. An error around the claim fails the run at once. Two writers of one keyword-rule row do not collide.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.composition import compose_statement_posting_dependencies
from src.database import create_session_maker_from_db
from src.extraction import (
    BankStatementStatus,
    RunKind,
    RunState,
    StatementSummary,
    TransactionDirection,
    reap_stale_runs,
)
from src.extraction.extension import statement_classification_run, statement_posting, transaction_classification
from src.extraction.extension.classification import ClassificationService
from src.extraction.extension.statement_classification_run import execute_classify_run
from src.extraction.extension.transaction_classification import (
    CategoryProposal,
    ClassificationOutcome,
    summarize_outcomes,
)
from src.extraction.orm.layer3 import TransactionClassification
from src.extraction.orm.statement_run import StatementRun
from src.llm import AIStreamError
from src.ledger import JournalEntry
from tests.extraction.test_statement_classify_run import (
    Proposer,
    _count,
    _high_confidence,
    _install,
    _model_on,  # noqa: F401 - the autouse fixture of the sibling module
    _parsing_job,
    _rows,
    _run,
    _seed,
)
from tests.extraction.test_statement_run_wiring import _runs, _statement, _use_case
from tests.statement_ingestion import classify_run_for, classify_statement

WAIT_SECONDS = 20
OFF_CATALOG = "PAYNOW TO JOHN TAN"
SECRET = "PAYNOW TO JOHN TAN 2500.00"


def _log_text(caplog) -> str:
    return "\n".join(f"{record.getMessage()} {record.msg!r} {record.exc_text or ''}" for record in caplog.records)


async def _moment_in(session, statement_id):
    """The committed state that a reader sees: the status, and whether a run is active (one statement, one snapshot)."""
    active = (
        select(StatementRun.id)
        .where(
            StatementRun.statement_id == StatementSummary.id,
            StatementRun.state.in_((RunState.REQUESTED, RunState.RUNNING)),
        )
        .exists()
    )
    row = (
        await session.execute(select(StatementSummary.status, active).where(StatementSummary.id == statement_id))
    ).one()
    return row[0], bool(row[1])


async def _moment(maker, statement_id):
    async with maker() as session:
        return await _moment_in(session, statement_id)


# --- A candidate keeps its run active until it is approved ---------------------------------------


async def test_AC_extraction_2994_107_a_candidate_keeps_its_run_active_until_it_is_approved(db, test_user, monkeypatch):
    """AC-extraction.2994.107: The status and the end of the run commit together: PARSED with no active run never shows."""
    _install(monkeypatch, Proposer())
    rows = _rows()
    service, content = _high_confidence(rows)
    statement_id, job = await _parsing_job(db, test_user, content)
    maker = create_session_maker_from_db(db)
    entered, gate = asyncio.Event(), asyncio.Event()
    real_finish = statement_classification_run.finish_run

    async def paused_finish(session, run_id, **kwargs):
        # This is the transaction of the auto-approve: the approve is flushed, nothing is committed yet.
        entered.set()
        await gate.wait()
        return await real_finish(session, run_id, **kwargs)

    monkeypatch.setattr(statement_classification_run, "finish_run", paused_finish)
    moments: set = set()
    polling = True

    async def poll() -> None:
        while polling:
            moments.add(await _moment(maker, statement_id))
            await asyncio.sleep(0.002)

    poller = asyncio.create_task(poll())
    task = asyncio.create_task(_use_case(db, service).execute(job, content=content))
    try:
        await asyncio.wait_for(entered.wait(), timeout=WAIT_SECONDS)
        async with maker() as other_session:
            assert await _moment_in(other_session, statement_id) == (BankStatementStatus.PARSED, True)
            classify = (await _runs(other_session, statement_id))[-1]
            assert (classify.kind, classify.state) == (RunKind.CLASSIFY, RunState.RUNNING)
            assert await _count(other_session, JournalEntry) == 0
    finally:
        gate.set()
    outcome = await asyncio.wait_for(task, timeout=WAIT_SECONDS)
    polling = False
    await poller

    assert outcome.auto_posted_count == len(rows)
    assert await _moment(maker, statement_id) == (BankStatementStatus.APPROVED, False)
    assert (BankStatementStatus.PARSED, False) not in moments, f"a reader saw PARSED without an active run: {moments}"
    assert (await _runs(db, statement_id))[-1].state is RunState.SUCCEEDED


async def test_AC_extraction_2994_107_a_manual_approve_before_the_auto_approve_gets_409(
    client, db, test_user, monkeypatch
):
    """AC-extraction.2994.107: The run is still active when its answers are committed: a manual approve is refused."""
    _install(monkeypatch, Proposer())
    rows = _rows()
    service, content = _high_confidence(rows)
    statement_id, job = await _parsing_job(db, test_user, content)
    entered, gate = asyncio.Event(), asyncio.Event()
    real = statement_classification_run.auto_approve_parsed_candidate

    async def paused(*args, **kwargs):
        entered.set()
        await gate.wait()
        return await real(*args, **kwargs)

    monkeypatch.setattr(statement_classification_run, "auto_approve_parsed_candidate", paused)
    task = asyncio.create_task(_use_case(db, service).execute(job, content=content))
    try:
        await asyncio.wait_for(entered.wait(), timeout=WAIT_SECONDS)
        classify = (await _runs(db, statement_id))[-1]
        assert (classify.kind, classify.state) == (RunKind.CLASSIFY, RunState.RUNNING)
        assert (await _statement(db, statement_id)).status is BankStatementStatus.PARSED

        refused = await client.post(f"/statements/{statement_id}/review/approve", json={})

        assert refused.status_code == 409, refused.text
        assert refused.json()["active_run_id"] == str(classify.id)
        assert await _count(db, JournalEntry) == 0
    finally:
        gate.set()
    outcome = await asyncio.wait_for(task, timeout=WAIT_SECONDS)

    assert outcome.auto_posted_count == len(rows)
    assert (await _statement(db, statement_id)).status is BankStatementStatus.APPROVED


@pytest.mark.parametrize("failure", ["error", "review"])
async def test_AC_extraction_2994_107_a_failed_auto_approve_still_ends_the_run_and_leaves_the_statement_parsed(
    db, test_user, monkeypatch, caplog, failure
):
    """AC-extraction.2994.107: An error, or a row for the economic review, leaves PARSED, posts nothing, and ends the run."""
    caplog.set_level(logging.DEBUG)
    if failure == "error":

        async def broken(*_args, **_kwargs):
            raise RuntimeError(SECRET)

        monkeypatch.setattr(statement_posting, "auto_create_posted_entries_for_statement", broken)
        _install(monkeypatch, Proposer())
    else:
        _install(monkeypatch, Proposer(refuse=frozenset({"Refund"})))
    service, content = _high_confidence(_rows())
    statement_id, job = await _parsing_job(db, test_user, content)

    outcome = await _use_case(db, service).execute(job, content=content)

    statement = await _statement(db, statement_id)
    extract, classify = await _runs(db, statement_id)
    assert outcome.auto_posted_count == 0
    assert statement.status is BankStatementStatus.PARSED
    assert await _count(db, JournalEntry) == 0
    assert (classify.kind, classify.state) == (RunKind.CLASSIFY, RunState.SUCCEEDED)
    assert classify.finished_at is not None and classify.result_summary["outcome"] in ("classified", "partial")
    if failure == "error":
        text = _log_text(caplog)
        assert "statement.auto_approve.failed" in text
        assert "PAYNOW" not in text and "2500.00" not in text


async def test_AC_extraction_2994_107_a_run_that_the_reaper_failed_during_the_auto_approve_undoes_the_approve(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.107: The finish of the run is in the transaction of the approve: a failed run rolls both back."""
    _install(monkeypatch, Proposer())
    service, content = _high_confidence(_rows())
    statement_id, job = await _parsing_job(db, test_user, content)
    maker = create_session_maker_from_db(db)
    real = statement_classification_run.auto_approve_parsed_candidate

    async def reaped_before_the_approve(*args, **kwargs):
        async with maker() as other_session:
            assert await reap_stale_runs(other_session, now=datetime.now(UTC) + timedelta(minutes=10))
            await other_session.commit()
        return await real(*args, **kwargs)

    monkeypatch.setattr(statement_classification_run, "auto_approve_parsed_candidate", reaped_before_the_approve)

    outcome = await _use_case(db, service).execute(job, content=content)

    classify = (await _runs(db, statement_id))[-1]
    assert outcome.auto_posted_count == 0
    assert (classify.state, classify.error_code) == (RunState.FAILED, "heartbeat_lost")
    assert (await _statement(db, statement_id)).status is BankStatementStatus.PARSED
    assert await _count(db, JournalEntry) == 0


# --- No row text and no driver detail ------------------------------------------------------------


def test_AC_extraction_2994_108_the_summary_counts_an_answer_outside_the_catalog_as_other():
    """AC-extraction.2994.108: Keys come from the closed catalog. Any other answer counts under the fixed key other."""
    outcomes = [
        ClassificationOutcome(
            atomic_txn_id=uuid4(), disposition="off_catalog", category=OFF_CATALOG, confidence=90, policy_version=1
        ),
        ClassificationOutcome(
            atomic_txn_id=uuid4(), disposition="off_catalog", category="OTHER ECHO", confidence=90, policy_version=1
        ),
        ClassificationOutcome(
            atomic_txn_id=uuid4(), disposition="applied", category="SALARY", confidence=95, policy_version=1
        ),
        ClassificationOutcome(
            atomic_txn_id=uuid4(), disposition="fallback", category="UNCLASSIFIED", confidence=0, policy_version=1
        ),
    ]

    assert summarize_outcomes(outcomes)["by_category"] == {"other": 2, "SALARY": 1, "UNCLASSIFIED": 1}


async def test_AC_extraction_2994_108_an_off_catalog_answer_that_equals_a_description_never_reaches_the_summary_or_a_log(
    db, test_user, monkeypatch, caplog
):
    """AC-extraction.2994.108: The answer text is model output. It can echo a row: no summary and no log holds it."""
    caplog.set_level(logging.DEBUG)
    rows = [
        {
            "description": OFF_CATALOG,
            "amount": Decimal("12.50"),
            "direction": TransactionDirection.OUT,
            "date": date(2026, 1, 5),
        },
        {
            "description": "Coffee 001",
            "amount": Decimal("3.50"),
            "direction": TransactionDirection.OUT,
            "date": date(2026, 1, 6),
        },
    ]

    async def echoing_model(transactions, _policy):
        return [
            CategoryProposal(
                category=OFF_CATALOG if t.description == OFF_CATALOG else "DINING", confidence=95, reason="x"
            )
            for t in transactions
        ]

    monkeypatch.setattr(transaction_classification, "propose_categories", echoing_model)
    seeded = await _seed(db, test_user, rows)

    run = await _run(db, await classify_statement(db, seeded.id))

    text = _log_text(caplog)
    assert "transaction classification pass" in text, "the log line of the pass was captured"
    assert run.result_summary["by_category"] == {"other": 1, "DINING": 1}
    assert OFF_CATALOG not in str(run.result_summary)
    assert OFF_CATALOG not in text


@pytest.mark.parametrize("where", ["classify_run", "provider_call"])
async def test_AC_extraction_2994_108_an_error_text_with_a_description_and_an_amount_never_reaches_a_log_or_the_run(
    db, test_user, monkeypatch, caplog, where
):
    """AC-extraction.2994.108: Logs carry the class of an error and a fixed message, never its text."""
    caplog.set_level(logging.DEBUG)
    if where == "classify_run":
        _install(monkeypatch, Proposer(error=RuntimeError(SECRET)))
        marker = "statement.classification.failed"
    else:

        def provider_down(**_kwargs):
            raise AIStreamError(SECRET)

        monkeypatch.setattr("src.llm.stream_ai_json", provider_down)
        marker = "transaction classification proposal failed"
    seeded = await _seed(db, test_user)

    run = await _run(db, await classify_statement(db, seeded.id))

    text = _log_text(caplog)
    assert marker in text, "the log line of the error was captured"
    assert "PAYNOW" not in text and "2500.00" not in text
    assert "PAYNOW" not in str(run.error_message) and "2500.00" not in str(run.error_message)
    assert "PAYNOW" not in str(run.result_summary)


# --- An error of this code never leaves the run requested ----------------------------------------


@pytest.mark.parametrize("where", ["parent_read", "claim"])
async def test_AC_extraction_2994_111_an_error_around_the_claim_fails_the_run_and_never_escapes(
    db, test_user, monkeypatch, caplog, where
):
    """AC-extraction.2994.111: Any error before the claim ends fails the run with the fixed code and message."""
    caplog.set_level(logging.DEBUG)
    proposer = _install(monkeypatch, Proposer())

    async def broken(*_args, **_kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(
        statement_classification_run, "_parent_marked_candidate" if where == "parent_read" else "claim_run", broken
    )
    seeded = await _seed(db, test_user)
    run_id = await classify_run_for(db, seeded.id)

    posted = await execute_classify_run(
        create_session_maker_from_db(db), run_id=run_id, posting_dependencies=compose_statement_posting_dependencies()
    )

    run = await _run(db, run_id)
    text = _log_text(caplog)
    assert posted == 0 and proposer.calls == []
    assert (run.state, run.error_code) == (RunState.FAILED, "classification_failed")
    assert "PAYNOW" not in str(run.error_message) and "PAYNOW" not in text
    assert "statement.classification.claim_failed" in text


# --- Two writers of one keyword-rule row -----------------------------------------------------------


async def test_AC_extraction_2994_112_two_writers_of_one_rule_row_do_not_collide(db, db_engine, test_user):
    """AC-extraction.2994.112: The second writer keeps the row of the first instead of failing with IntegrityError."""
    from tests.extraction.test_statement_classify_run import _add_coffee_rule

    seeded = await _seed(db, test_user)
    await _add_coffee_rule(db, test_user)
    coffee = next(txn for txn in seeded.transactions if txn.description.startswith("Coffee"))
    coffee_id, user_id = coffee.id, test_user.id
    maker = create_session_maker_from_db(db)

    async with maker() as first, maker() as second:
        first_rows = await ClassificationService().apply_rules(
            first, user_id, [await first.get(type(coffee), coffee_id)]
        )
        second_task = asyncio.create_task(
            ClassificationService().apply_rules(second, user_id, [await second.get(type(coffee), coffee_id)])
        )
        done, _pending = await asyncio.wait({second_task}, timeout=0.5)
        assert not done, "the second writer waits for the unique index while the first has not committed"
        await first.commit()
        second_rows = await asyncio.wait_for(second_task, timeout=WAIT_SECONDS)
        await second.commit()

    assert [row.id for row in second_rows] == [row.id for row in first_rows]
    assert await _count(db, TransactionClassification, TransactionClassification.atomic_txn_id == coffee_id) == 1
