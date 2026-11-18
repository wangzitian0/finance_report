"""A poster and a classify run never wait for each other in a cycle (#2994, third review of S4b-1).

The poster is the auto-fill of the approve: for each row it posts a reviewed disposition and settles the draft.
The posting locks the row of the transaction and the counter account, then the settle updates the draft. The batch
write of a re-ask locks the draft first, then inserts the new answer, and that insert takes FOR KEY SHARE on the
transaction row and on the account. A FOR UPDATE lock of the poster blocks that check: the poster waits for the
draft, the run waits for the row, and Postgres aborts one of them. FOR NO KEY UPDATE does not block it.
The second guard is the order of the approve: it takes the statement lock before it looks for an active run.
The tests use real sessions and a short `lock_timeout`, so a cycle fails in seconds.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.composition import (
    auto_fill_default_statement_dispositions,
    compose_reviewed_disposition_dependencies,
    compose_statement_posting_dependencies,
)
from src.config import settings
from src.extraction import (
    ActiveRunExists,
    AtomicTransaction,
    BankStatementStatus,
    ClassificationStatus,
    EconomicIntent,
    RunState,
    StatementSummary,
    approve_statement_workflow,
    settle_drafts_after_posting,
    start_user_classify_run,
)
from src.extraction.extension import transaction_classification as tc
from src.extraction.extension.statement_runs import StatementStatusChanged
from src.ledger import Account, AccountType, JournalEntry
from src.reconciliation import (
    NamedTransfer,
    ReviewedDispositionCommand,
    post_named_transfer_legs,
    submit_reviewed_disposition,
)
from tests.extraction.test_statement_classify_reask import (
    ANSWERS,
    HINTS,
    ReaskModel,
    _answer,
    _classified_statement,
    _history,
    _install,
    _model_on,  # noqa: F401 - the autouse fixture of the sibling module
    _run,
    _user_run,
)
from tests.extraction.test_statement_classify_reask_ledger_and_locks import (
    DRAFT_CONFIDENCE,
    WAIT_SECONDS,
    _lock_waiters,
    _txn,
)
from tests.extraction.test_statement_classify_run import _rows, _seed
from tests.extraction.test_statement_classify_run_phases import _wait_until, _worker

LOCK_TIMEOUT_MS = 8000


@pytest_asyncio.fixture
async def maker(db_engine):
    """Sessions of the test engine, so the cleanup sees their writes. A lock wait ends after 8 s: a hang is an error."""

    def give_up_a_lock_wait(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET lock_timeout = {LOCK_TIMEOUT_MS}")
        cursor.close()

    event.listen(db_engine.sync_engine, "connect", give_up_a_lock_wait)
    try:
        yield async_sessionmaker(db_engine, expire_on_commit=False)
    finally:
        event.remove(db_engine.sync_engine, "connect", give_up_a_lock_wait)


async def _link_a_bank(db, user, statement) -> None:
    """The statement needs an account of its own for a poster to post into it."""
    bank = Account(user_id=user.id, name="Bank of a poster", type=AccountType.ASSET, currency="SGD")
    db.add(bank)
    await db.flush()
    statement.account_id = bank.id
    await db.commit()


async def _post_a_reviewed_disposition(poster, user, txn, draft) -> None:
    """The row and the counter account are locked now. The counter account is the account of the draft."""
    await submit_reviewed_disposition(
        poster,
        transaction_id=txn.id,
        user_id=user.id,
        command=ReviewedDispositionCommand(
            intent=EconomicIntent.EXPENSE,
            counter_account_id=draft.account_id,
            category="GENERAL",
            rationale="Reviewed.",
        ),
        dependencies=compose_reviewed_disposition_dependencies(poster),
    base_currency='SGD',)


async def _post_a_named_transfer(poster, user, txn, _draft) -> None:
    """The row is locked now, by the claim of the reconciliation repository."""
    row = await poster.get(AtomicTransaction, txn.id)
    legs = await post_named_transfer_legs(poster, user_id=user.id, named=[NamedTransfer(row, "TRANSFER", 88)], base_currency='SGD')
    assert len(legs) == 1


@pytest.mark.parametrize(
    "post", [_post_a_reviewed_disposition, _post_a_named_transfer], ids=["reviewed_disposition", "named_transfer"]
)
async def test_AC_extraction_2994_152_a_poster_that_holds_the_row_does_not_deadlock_with_the_batch_write(
    db, maker, test_user, monkeypatch, post
):
    """AC-extraction.2994.152: The poster holds the row. The batch write inserts its answer and both end."""
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", False)
    seeded, _auto_run_id, _automatic = await _classified_statement(
        db, test_user, monkeypatch, model=ReaskModel(confidence=DRAFT_CONFIDENCE)
    )
    draft = await _answer(db, test_user, "Grab")
    assert draft.status is ClassificationStatus.DRAFT and draft.account_id is not None
    txn = _txn(seeded, "Grab")
    await _link_a_bank(db, test_user, seeded.statement)
    _install(monkeypatch, ReaskModel())
    run_id = await _user_run(db, seeded.id, test_user)
    entered, release = asyncio.Event(), asyncio.Event()
    original = tc._supersede_older_model_rows

    async def pause_after_the_insert(db_, user_id, txn_ids, version):
        if txn_ids:  # the batch write: the draft is locked and the new answer is inserted, nothing is committed
            entered.set()
            await release.wait()
        return await original(db_, user_id, txn_ids, version)

    monkeypatch.setattr(tc, "_supersede_older_model_rows", pause_after_the_insert)
    worker = settle = None
    poster_error: BaseException | None = None
    try:
        async with maker() as poster:
            await post(poster, test_user, txn, draft)
            worker = asyncio.create_task(_worker(maker, run_id))

            async def run_is_at_the_row() -> bool:  # the run is paused after its insert, or it waits for the row
                return entered.is_set() or bool(await _lock_waiters(maker, "transactionid", "tuple"))

            assert await _wait_until(run_is_at_the_row, 10.0), "the run reached neither the insert nor a wait"
            settle = asyncio.create_task(settle_drafts_after_posting(poster, txn.id, accepted_id=draft.id))

            async def poster_waits_for_the_draft() -> bool:  # one waiter if the run is paused, two if it also waits
                waiters = await _lock_waiters(maker, "transactionid", "tuple")
                return settle.done() or waiters >= (1 if entered.is_set() else 2)

            assert await _wait_until(poster_waits_for_the_draft, 10.0)
            release.set()
            try:
                await asyncio.wait_for(settle, timeout=WAIT_SECONDS)
                await poster.commit()
            except Exception as exc:  # noqa: BLE001 - the test reports the error class below
                poster_error = exc
                await poster.rollback()
    finally:
        release.set()
        for task in (settle, worker):
            if task is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(task, timeout=WAIT_SECONDS)

    assert poster_error is None, f"the poster failed: {type(poster_error).__name__} {poster_error}"
    run = await _run(db, run_id)
    assert (run.state, run.error_code) == (RunState.SUCCEEDED, None), "the run failed while the poster held the row"
    old, new = await _history(db, test_user, "Grab")
    assert (old.status, new.status) == (ClassificationStatus.SUPERSEDED, ClassificationStatus.APPLIED)
    assert new.tags["run_id"] == str(run_id), "the answer of the run is the live one"
    entries = await db.scalar(
        select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == test_user.id)
    )
    assert entries == 1, "the poster posted its entry"


async def _drafts_that_the_auto_fill_posts(db, test_user, monkeypatch):
    """A parsed statement with a bank account, whose rows have no answer. The inline answers are drafts."""
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", False)
    seeded = await _seed(db, test_user, _rows(5))
    await _link_a_bank(db, test_user, seeded.statement)
    _install(monkeypatch, ReaskModel(confidence=dict.fromkeys(ANSWERS, 75)))
    return seeded


async def test_AC_extraction_2994_153_the_auto_fill_takes_the_statement_lock_before_it_looks_for_a_run(
    db, maker, test_user, monkeypatch
):
    """AC-extraction.2994.153: A run start holds the statement lock. The auto-fill waits, then refuses with the run id."""
    seeded = await _drafts_that_the_auto_fill_posts(db, test_user, monkeypatch)
    statement_id = seeded.id
    fill = None
    try:
        async with maker() as starter:
            run_id = await start_user_classify_run(
                starter, statement_id=statement_id, user_id=test_user.id, hints=HINTS
            )

            async def auto_fill() -> int:
                async with maker() as filler:
                    statement = await filler.get(StatementSummary, statement_id)
                    return await auto_fill_default_statement_dispositions(filler, statement, test_user.id)

            fill = asyncio.create_task(auto_fill())

            async def fill_waits() -> bool:
                return fill.done() or bool(await _lock_waiters(maker, "transactionid", "tuple"))

            assert await _wait_until(fill_waits, 10.0)
            assert not fill.done(), f"the auto-fill ended before the run start committed: {fill.result()}"
            await starter.commit()
        with pytest.raises(ActiveRunExists) as refused:
            await asyncio.wait_for(fill, timeout=WAIT_SECONDS)
    finally:
        if fill is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(fill, timeout=WAIT_SECONDS)

    assert refused.value.active_run_id == run_id
    posted = await db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == test_user.id))
    assert posted == 0, "the refused auto-fill posted nothing"
    assert (await _run(db, run_id)).state is RunState.REQUESTED


async def test_AC_extraction_2994_154_a_run_start_waits_for_the_approve_and_the_lock_upgrade_does_not_deadlock(
    db, maker, test_user, monkeypatch
):
    """AC-extraction.2994.154: The auto-fill holds the lock, the run start waits, the approve upgrades and commits."""
    seeded = await _drafts_that_the_auto_fill_posts(db, test_user, monkeypatch)
    statement_id = seeded.id
    start = None

    async def start_a_run() -> object:
        async with maker() as starter:
            return await start_user_classify_run(starter, statement_id=statement_id, user_id=test_user.id, hints=HINTS)

    try:
        async with maker() as approver:
            statement = await approver.get(StatementSummary, statement_id)
            filled = await auto_fill_default_statement_dispositions(approver, statement, test_user.id)
            assert filled == 5, "the auto-fill posted its rows and holds the statement lock"
            start = asyncio.create_task(start_a_run())

            async def start_waits() -> bool:
                return start.done() or bool(await _lock_waiters(maker, "transactionid", "tuple"))

            assert await _wait_until(start_waits, 10.0)
            assert not start.done(), "the run start must wait for the approve that holds the statement lock"
            await approve_statement_workflow(
                approver, statement_id, test_user.id, dependencies=compose_statement_posting_dependencies()
            )
        with pytest.raises(StatementStatusChanged):
            await asyncio.wait_for(start, timeout=WAIT_SECONDS)
    finally:
        if start is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(start, timeout=WAIT_SECONDS)

    await db.rollback()
    statement = await db.get(StatementSummary, statement_id, populate_existing=True)
    assert statement.status is BankStatementStatus.APPROVED, "the approve committed"
