"""A re-ask never writes over the ledger or over a decision of the user (#2994, second review of S4b-1).

Two things protect a row: the rows that the ledger covers (an anchored entry, a legacy entry, an accepted transfer
match) and the decisions of the user (`corrected_by_user`, `rejected_by_user`, `accepted_by_user`). The plan reads
both, and the batch write reads both again after the policy-rule key, from the rows that it locks, because the
model call lasts seconds and a request of the user or a posting can commit in that time. The race tests use real
sessions: one session holds the key or a row, the run waits, the session commits, and the marker must stay.
"""

from __future__ import annotations

import asyncio
import contextlib
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from src.audit import JournalEntrySourceType
from src.composition import compose_reviewed_disposition_dependencies
from src.config import settings
from src.database import create_session_maker_from_db
from src.extraction import (
    ClassificationStatus,
    EconomicIntent,
    RunState,
    apply_suggestion_feedback,
    settle_drafts_after_posting,
)
from src.extraction.extension import transaction_classification as tc
from src.ledger import Account, AccountType, JournalEntry, JournalEntryStatus, void_journal_entry
from src.reconciliation import ReconciliationMatch, ReconciliationStatus, ReviewedDispositionCommand, submit_reviewed_disposition
from tests.extraction.test_statement_classify_reask import (
    ANSWERS,
    ReaskModel,
    _answer,
    _classified_statement,
    _history,
    _install,
    _model_on,  # noqa: F401 - the autouse fixture of the sibling module
    _run,
    _user_run,
)
from tests.extraction.test_statement_classify_run_phases import _wait_until, _worker

WAIT_SECONDS = 20
DRAFT_CONFIDENCE = {"Grab": 75}  # between the review and the auto-apply threshold: the answer is a draft


def _txn(seeded, kind: str):
    return next(txn for txn in seeded.transactions if txn.description.startswith(kind))


def _accepted_transfer(db, user, txn) -> None:
    """The match that a transfer leg gets: the posting and the re-ask both skip a row with a live accepted match."""
    db.add(
        ReconciliationMatch(
            atomic_txn_id=txn.id,
            journal_entry_ids=[str(uuid4())],
            match_score=90,
            status=ReconciliationStatus.AUTO_ACCEPTED,
        )
    )


def _legacy_entry(db, user, txn) -> None:
    """An entry that was posted before anchors existed: it has the row as its source and no anchor."""
    db.add(
        JournalEntry(
            user_id=user.id,
            entry_date=txn.txn_date,
            memo="Posted before anchors",
            source_type=JournalEntrySourceType.AUTO_PARSED,
            source_id=txn.id,
        )
    )


async def _lock_waiters(maker, *events: str) -> int:
    """How many sessions of this database wait for a lock of one of these kinds right now."""
    async with maker() as probe:  # its own session: the test session keeps its objects
        return await probe.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND wait_event_type = 'Lock' AND wait_event = ANY(:events)"
            ),
            {"events": list(events)},
        )


async def _waiting(maker, *events: str) -> bool:
    """Whether a session of this database waits for a lock of one of these kinds. The caller asserts the result."""

    async def blocked() -> bool:
        return bool(await _lock_waiters(maker, *events))

    return await _wait_until(blocked, seconds=10.0)


async def _kept_as_it_was(db, user, kind: str, before: tuple) -> None:
    rows = await _history(db, user, kind)
    assert len(rows) == 1, f"{kind} got {len(rows)} answers: the run wrote for a row that it must skip"
    assert (rows[0].id, rows[0].status, rows[0].tags) == before


async def _snapshot(db, user, kind: str) -> tuple:
    row = await _answer(db, user, kind)
    return row.id, row.status, dict(row.tags)


@pytest.mark.parametrize("cover", [_accepted_transfer, _legacy_entry], ids=["transfer_match", "legacy_entry"])
async def test_AC_extraction_2994_145_a_row_that_the_ledger_covers_is_not_asked_again(
    db, test_user, monkeypatch, cover
):
    """AC-extraction.2994.145: A transfer match or a legacy entry covers the row. The run neither asks it nor writes it."""
    seeded, _auto_run_id, _automatic = await _classified_statement(db, test_user, monkeypatch)
    before = await _snapshot(db, test_user, "Grab")
    cover(db, test_user, _txn(seeded, "Grab"))
    await db.commit()
    reasked = _install(monkeypatch, ReaskModel())
    run_id = await _user_run(db, seeded.id, test_user)

    await _worker(create_session_maker_from_db(db), run_id)

    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
    assert reasked.asked_kinds == set(ANSWERS) - {"Grab"}
    await _kept_as_it_was(db, test_user, "Grab", before)
    assert len(await _history(db, test_user, "Salary")) == 2


async def test_AC_extraction_2994_146_a_row_that_the_user_accepted_is_not_asked_again(db, test_user, monkeypatch):
    """AC-extraction.2994.146: The accept of a draft marks it accepted_by_user. A user run does not ask it again."""
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", False)
    seeded, _auto_run_id, _automatic = await _classified_statement(
        db, test_user, monkeypatch, model=ReaskModel(confidence=DRAFT_CONFIDENCE)
    )
    draft = await _answer(db, test_user, "Grab")
    assert draft.status is ClassificationStatus.DRAFT
    await settle_drafts_after_posting(db, draft.atomic_txn_id, accepted_id=draft.id)
    await db.commit()
    before = await _snapshot(db, test_user, "Grab")
    assert before[1] is ClassificationStatus.APPLIED and before[2]["accepted_by_user"] is True
    reasked = _install(monkeypatch, ReaskModel())
    run_id = await _user_run(db, seeded.id, test_user)

    await _worker(create_session_maker_from_db(db), run_id)

    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
    assert reasked.asked_kinds == set(ANSWERS) - {"Grab"}
    await _kept_as_it_was(db, test_user, "Grab", before)


async def test_AC_extraction_2994_147_a_row_that_the_ledger_covers_after_the_plan_is_not_written(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.147: A match commits during the model call. The batch write checks again and skips the row."""
    seeded, _auto_run_id, _automatic = await _classified_statement(db, test_user, monkeypatch)
    before = await _snapshot(db, test_user, "Grab")
    maker = create_session_maker_from_db(db)

    async def cover_while_the_model_runs(_number, transactions):
        grab = next(txn for txn in transactions if txn.description.startswith("Grab"))
        async with maker() as other:
            _accepted_transfer(other, test_user, grab)
            await other.commit()

    asked = _install(monkeypatch, ReaskModel(during=cover_while_the_model_runs))
    run_id = await _user_run(db, seeded.id, test_user)

    await _worker(maker, run_id)

    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
    assert asked.asked_kinds == set(ANSWERS), "the plan did not know the match: the model was asked for the row"
    await _kept_as_it_was(db, test_user, "Grab", before)
    assert len(await _history(db, test_user, "Salary")) == 2, "the other rows got their new answers"


async def test_AC_extraction_2994_148_a_feedback_that_holds_the_policy_key_keeps_its_marker(db, test_user, monkeypatch):
    """AC-extraction.2994.148: The feedback holds the key and has not committed. The batch waits, then skips the row."""
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", False)
    seeded, auto_run_id, _automatic = await _classified_statement(
        db, test_user, monkeypatch, model=ReaskModel(confidence=DRAFT_CONFIDENCE)
    )
    draft = await _answer(db, test_user, "Grab")
    maker = create_session_maker_from_db(db)
    _install(monkeypatch, ReaskModel())
    run_id = await _user_run(db, seeded.id, test_user)
    worker = None
    try:
        async with maker() as feedback:
            effect = await apply_suggestion_feedback(
                feedback, test_user.id, draft.id, "edit_accept", {"value": "groceries"}
            )
            assert effect == "corrected"
            worker = asyncio.create_task(_worker(maker, run_id))
            assert await _waiting(maker, "advisory"), "the batch write waits for the policy-rule key"
            await feedback.commit()
    finally:
        if worker is not None:
            await asyncio.wait_for(worker, timeout=WAIT_SECONDS)

    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
    rows = await _history(db, test_user, "Grab")
    assert len(rows) == 1, "the run wrote a new answer over the correction"
    assert (rows[0].tags["category"], rows[0].tags["corrected_by_user"]) == ("GROCERIES", True)
    assert rows[0].tags["run_id"] == str(auto_run_id) and rows[0].status is ClassificationStatus.DRAFT
    assert len(await _history(db, test_user, "Salary")) == 2


async def test_AC_extraction_2994_148_a_posting_that_holds_only_the_row_keeps_its_marker(db, test_user, monkeypatch):
    """AC-extraction.2994.148: A writer without the key holds the row. The batch locks the row, reads it, skips it."""
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", False)
    seeded, auto_run_id, _automatic = await _classified_statement(
        db, test_user, monkeypatch, model=ReaskModel(confidence=DRAFT_CONFIDENCE)
    )
    draft = await _answer(db, test_user, "Grab")
    maker = create_session_maker_from_db(db)
    _install(monkeypatch, ReaskModel())
    run_id = await _user_run(db, seeded.id, test_user)
    worker = None
    try:
        async with maker() as posting:
            await settle_drafts_after_posting(posting, draft.atomic_txn_id, accepted_id=draft.id)
            worker = asyncio.create_task(_worker(maker, run_id))
            assert await _waiting(maker, "transactionid", "tuple"), "the batch write waits for the row"
            await posting.commit()
    finally:
        if worker is not None:
            await asyncio.wait_for(worker, timeout=WAIT_SECONDS)

    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
    rows = await _history(db, test_user, "Grab")
    assert len(rows) == 1, "the run wrote a new answer for a row that the user accepted"
    assert (rows[0].status, rows[0].tags["accepted_by_user"]) == (ClassificationStatus.APPLIED, True)
    assert rows[0].tags["run_id"] == str(auto_run_id)


async def test_AC_extraction_2994_148_a_feedback_that_arrives_while_the_batch_holds_the_rows_waits_for_the_key(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.148: The batch holds the key and the rows. The feedback waits at the key and ends cleanly."""
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", False)
    seeded, _auto_run_id, _automatic = await _classified_statement(
        db, test_user, monkeypatch, model=ReaskModel(confidence=DRAFT_CONFIDENCE)
    )
    draft = await _answer(db, test_user, "Grab")
    maker = create_session_maker_from_db(db)
    _install(monkeypatch, ReaskModel())
    run_id = await _user_run(db, seeded.id, test_user)
    entered, release = asyncio.Event(), asyncio.Event()
    original = tc._supersede_older_model_rows

    async def hold_the_locks(db_, user_id, txn_ids, version):
        if txn_ids:  # the batch write: the key and the row locks are held and nothing is committed
            entered.set()
            await release.wait()
        return await original(db_, user_id, txn_ids, version)

    monkeypatch.setattr(tc, "_supersede_older_model_rows", hold_the_locks)
    worker = asyncio.create_task(_worker(maker, run_id))
    feedback_task = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=WAIT_SECONDS)
        async with maker() as feedback:
            feedback_task = asyncio.create_task(
                apply_suggestion_feedback(feedback, test_user.id, draft.id, "edit_accept", {"value": "groceries"})
            )
            assert await _waiting(maker, "advisory"), "the feedback waits at the policy-rule key, not at the row"
            release.set()
            effect = await asyncio.wait_for(feedback_task, timeout=WAIT_SECONDS)
            await feedback.commit()
    finally:
        release.set()
        for task in (feedback_task, worker):
            if task is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(task, timeout=WAIT_SECONDS)

    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
    assert effect == "recorded", "the draft was superseded before the feedback got the row"
    old, new = await _history(db, test_user, "Grab")
    assert (old.status, new.status) == (ClassificationStatus.SUPERSEDED, ClassificationStatus.APPLIED)
    assert "corrected_by_user" not in new.tags and "corrected_by_user" not in old.tags


async def test_AC_extraction_3057_void_journal_entry_does_not_block_reask(db, test_user, monkeypatch):
    """#3057 Case 4: A VOID journal entry is not covered by the ledger, so re-ask still classifies the row."""
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", False)
    seeded, _auto_run_id, _automatic = await _classified_statement(
        db, test_user, monkeypatch, model=ReaskModel(confidence=DRAFT_CONFIDENCE)
    )
    grab_txn = _txn(seeded, "Grab")
    draft = await _answer(db, test_user, "Grab")
    bank = Account(user_id=test_user.id, name="Bank of void test", type=AccountType.ASSET, currency="SGD")
    db.add(bank)
    await db.flush()
    seeded.statement.account_id = bank.id
    await db.flush()
    await submit_reviewed_disposition(
        db,
        transaction_id=grab_txn.id,
        user_id=test_user.id,
        command=ReviewedDispositionCommand(
            intent=EconomicIntent.EXPENSE,
            counter_account_id=draft.account_id,
            category="GENERAL",
            rationale="Posted before voiding.",
        ),
        dependencies=compose_reviewed_disposition_dependencies(db),
    base_currency='SGD',)
    posted_entry = await db.scalar(select(JournalEntry).where(JournalEntry.source_id == grab_txn.id))
    assert posted_entry is not None
    await void_journal_entry(db, posted_entry.id, "Voided before re-ask", test_user.id)
    await db.commit()
    assert posted_entry.status is JournalEntryStatus.VOID

    reasked = _install(monkeypatch, ReaskModel())
    run_id = await _user_run(db, seeded.id, test_user)

    await _worker(create_session_maker_from_db(db), run_id)

    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
    assert "Grab" in reasked.asked_kinds
    assert len(await _history(db, test_user, "Grab")) == 2
