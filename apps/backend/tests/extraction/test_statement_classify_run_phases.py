"""A classify run holds no transaction, row lock or connection while a model call runs (#3028, #2994).

The run reads in a short session, writes the keyword-rule answers and commits, asks the model for each batch with no
session, and writes the answers of each batch in its own short transaction. A failure, a deadline or a reaper keeps
the batches that are already written. The tests use real sessions and a private pool, so a held connection or lock shows.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.composition import compose_statement_posting_dependencies
from src.database import create_app_engine, create_session_maker_from_db
from src.extraction import BankStatementStatus, RunState, reap_stale_runs
from src.extraction.extension import statement_runs, transaction_classification
from src.extraction.extension.statement_classification_run import execute_classify_run
from src.extraction.extension.transaction_classification import (
    CLASSIFICATION_PHASE_DEADLINE_SECONDS,
    POLICY_RULE_NAME,
    CategoryProposal,
    ClassificationPolicy,
    classify_by_effective_policy,
)
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import TransactionClassification
from src.ledger import JournalEntry
from tests.extraction.test_statement_classify_run import (
    ANSWERS,
    _add_coffee_rule,
    _answers,
    _count,
    _install,
    _model_on,  # noqa: F401 - the autouse fixture of the sibling module
    _rows,
    _run,
    _seed,
)
from tests.extraction.test_statement_run_wiring import _statement
from tests.statement_ingestion import classify_run_for, classify_statement

WAIT_SECONDS = 20
SECRET = "PAYNOW TO JOHN TAN 2500.00"


class ScriptedModel:
    """A model that handles each call by its number.

    A step is None (answer at once), an Event (wait for it, then answer), an exception (raise it) or a coroutine
    function (await it, then answer). A call after the last step answers at once.
    """

    def __init__(self, *steps) -> None:
        self.steps = steps
        self.calls: list[list[str]] = []
        self._reached: dict[int, asyncio.Event] = {}

    def reached(self, number: int) -> asyncio.Event:
        return self._reached.setdefault(number, asyncio.Event())

    async def __call__(self, transactions, _policy):
        number = len(self.calls)
        self.calls.append([transaction.description for transaction in transactions])
        self.reached(number).set()
        step = self.steps[number] if number < len(self.steps) else None
        if isinstance(step, asyncio.Event):
            await asyncio.wait_for(step.wait(), timeout=WAIT_SECONDS)
        elif isinstance(step, BaseException):
            raise step
        elif step is not None:
            await step()
        return [
            CategoryProposal(
                category=ANSWERS[transaction.description.split()[0]][0].value,
                confidence=ANSWERS[transaction.description.split()[0]][1],
                reason="fixture",
            )
            for transaction in transactions
        ]


@pytest.fixture(autouse=True)
def _small_serial_batches(monkeypatch):
    """Two rows to a batch, one batch at a time, so the order of the calls is the order of the batches."""
    monkeypatch.setattr(transaction_classification, "CLASSIFICATION_BATCH_SIZE", 2)
    monkeypatch.setattr(transaction_classification, "CLASSIFICATION_PARALLEL_BATCHES", 1)


def _worker(maker, run_id: UUID, **options):
    return execute_classify_run(
        maker, run_id=run_id, posting_dependencies=compose_statement_posting_dependencies(), **options
    )


async def _answered_descriptions(db, user) -> set[str]:
    rows = await db.execute(
        select(AtomicTransaction.description)
        .join(TransactionClassification, TransactionClassification.atomic_txn_id == AtomicTransaction.id)
        .where(AtomicTransaction.user_id == user.id)
    )
    return set(rows.scalars())


async def _wait_until(condition, seconds: float = 10.0) -> bool:
    """Poll an async condition. Return whether it became true. The caller asserts the result."""
    deadline = asyncio.get_running_loop().time() + seconds
    while not await condition():
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(0.02)
    return True


async def _written_rows(db, user, count: int) -> bool:
    return await _answers(db, user) >= count


# --- No transaction, row lock or connection is held while the model call runs ----------------------------


@pytest_asyncio.fixture
async def blocked(db, db_engine, test_user, test_database_url, monkeypatch):
    """A run whose second model call waits. The first call answered the four rows of policy 1 and was written."""
    first, second = transaction_classification.POLICY_VERSIONS
    monkeypatch.setattr(
        transaction_classification,
        "POLICY_VERSIONS",
        (
            ClassificationPolicy(**{**first.model_dump(), "effective_from": date.min}),
            ClassificationPolicy(**{**second.model_dump(), "effective_from": date(2026, 1, 6)}),
        ),
    )
    seeded = await _seed(db, test_user, _rows(10))
    await _add_coffee_rule(db, test_user)
    gate = asyncio.Event()
    model = _install(monkeypatch, ScriptedModel(None, gate))
    run_id = await classify_run_for(db, seeded.id)
    engine = create_app_engine(test_database_url, pool_size=4, max_overflow=0)
    worker = asyncio.create_task(_worker(async_sessionmaker(engine, expire_on_commit=False), run_id))
    try:
        await asyncio.wait_for(model.reached(1).wait(), timeout=WAIT_SECONDS)

        async def written() -> bool:
            return await _answers(db, test_user) == 5

        async def idle() -> bool:
            return engine.pool.checkedout() == 0

        # The answers of call 0 and the keyword-rule answer are written. A held connection never becomes idle.
        await _wait_until(written)
        await _wait_until(idle)
        yield SimpleNamespace(
            engine=engine,
            db_engine=db_engine,
            user_id=test_user.id,
            model_answered_id=seeded.transactions[0].id,
            rule_answered_id=seeded.transactions[1].id,
        )
    finally:
        gate.set()
        await asyncio.wait_for(worker, timeout=WAIT_SECONDS)
        await engine.dispose()


async def _row_is_free(engine, txn_id) -> bool:
    async with AsyncSession(engine) as other:
        try:
            await other.execute(select(AtomicTransaction.id).where(AtomicTransaction.id == txn_id).with_for_update(nowait=True))
        except Exception:  # noqa: BLE001 - the driver raises LockNotAvailableError for a held row
            return False
        return True


def _lock_key(user_id: UUID, version: int) -> str:
    return f"policy_rule:{user_id}:{POLICY_RULE_NAME}:{version}"


async def _lock_is_free(engine, user_id: UUID, version: int) -> bool:
    async with engine.connect() as connection:
        got = await connection.scalar(
            select(func.pg_try_advisory_xact_lock(func.hashtextextended(_lock_key(user_id, version), 0)))
        )
        return bool(got)


async def test_AC_extraction_2994_117_a_second_connection_can_lock_the_rows_of_the_run_during_the_model_call(blocked):
    """AC-extraction.2994.117: The rows that the keyword rule and the first batch answered are free during call 2."""
    assert await _row_is_free(blocked.db_engine, blocked.rule_answered_id), "the keyword-rule row is locked"
    assert await _row_is_free(blocked.db_engine, blocked.model_answered_id), "the row of the first batch is locked"


async def test_AC_extraction_2994_117_the_key_of_the_lock_probe_is_the_key_of_the_policy_rule_lock(db, db_engine, test_user):
    """AC-extraction.2994.117: Control of the probe: a lock that the product takes is not free for the probe."""
    policy = transaction_classification.policy_for(date(2026, 1, 1))
    async with AsyncSession(db_engine) as holder:
        await transaction_classification._lock_policy_rule(holder, test_user.id, policy)
        assert not await _lock_is_free(db_engine, test_user.id, policy.version)
        assert await _lock_is_free(db_engine, test_user.id, policy.version + 1)


async def test_AC_extraction_2994_117_a_second_connection_can_take_the_policy_rule_lock_during_the_model_call(blocked):
    """AC-extraction.2994.117: The lock of the older policy version is free while the model call of the newer one runs."""
    assert await _lock_is_free(blocked.db_engine, blocked.user_id, 1), "the lock of policy 1 is held"
    assert await _lock_is_free(blocked.db_engine, blocked.user_id, 2), "the lock of policy 2 is held"


async def test_AC_extraction_2994_117_the_pool_of_the_run_has_no_checked_out_connection_during_the_model_call(blocked):
    """AC-extraction.2994.117: The run owns no connection while it waits for the model."""
    for _sample in range(4):
        assert blocked.engine.pool.checkedout() == 0, "the run holds a pooled connection during the model call"
        await asyncio.sleep(0.05)


# --- The keyword-rule answers are committed before the first model call ----------------------------------


async def test_AC_extraction_2994_118_the_keyword_rule_answer_is_committed_before_the_first_model_call(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.118: Another session sees the rule answer while the first model call waits."""
    seeded = await _seed(db, test_user, _rows(5))
    await _add_coffee_rule(db, test_user)
    gate = asyncio.Event()
    model = _install(monkeypatch, ScriptedModel(gate))
    run_id = await classify_run_for(db, seeded.id)
    worker = asyncio.create_task(_worker(create_session_maker_from_db(db), run_id))
    try:
        await asyncio.wait_for(model.reached(0).wait(), timeout=WAIT_SECONDS)
        assert await _answered_descriptions(db, test_user) == {"Coffee 001"}
    finally:
        gate.set()
        await asyncio.wait_for(worker, timeout=WAIT_SECONDS)
    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
    assert await _answers(db, test_user) == 5


# --- A batch of a run that the reaper failed is not written ----------------------------------------------


async def test_AC_extraction_2994_95_a_batch_of_a_run_that_the_reaper_failed_is_not_written(db, test_user, monkeypatch):
    """AC-extraction.2994.95: The reaper fails the run during batch 2: batch 1 stays, batch 2 writes nothing."""
    seeded = await _seed(db, test_user)
    run_id = await classify_run_for(db, seeded.id)
    maker = create_session_maker_from_db(db)

    async def reaped_during_the_call():
        assert await _wait_until(lambda: _written_rows(db, test_user, 2)), "batch 1 was not written"
        async with maker() as other_session:
            assert await reap_stale_runs(other_session, now=datetime.now(UTC) + timedelta(minutes=10)) == [run_id]
            await other_session.commit()

    model = _install(monkeypatch, ScriptedModel(None, reaped_during_the_call))

    posted = await _worker(maker, run_id)

    run = await _run(db, run_id)
    assert posted == 0
    assert (run.state, run.error_code) == (RunState.FAILED, "heartbeat_lost")
    assert await _answered_descriptions(db, test_user) == set(model.calls[0])
    assert await _count(db, JournalEntry) == 0
    assert (await _statement(db, seeded.id)).status is BankStatementStatus.PARSED


# --- A failed run keeps the batches that it wrote, and the next run asks only the rest -------------------


async def test_AC_extraction_2994_116_a_failed_batch_keeps_the_earlier_batches_and_the_next_run_asks_only_the_rest(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.116: Batch 1 is written, batch 2 raises. The next run asks for the three rows without an answer."""
    seeded = await _seed(db, test_user)
    every_row = {transaction.description for transaction in seeded.transactions}
    failing = _install(monkeypatch, ScriptedModel(None, RuntimeError(SECRET)))

    run_id = await classify_statement(db, seeded.id)

    run = await _run(db, run_id)
    written = set(failing.calls[0])
    assert (run.state, run.error_code) == (RunState.FAILED, "classification_failed")
    assert len(written) == 2 and await _answered_descriptions(db, test_user) == written
    assert run.result_summary["batches_done"] == 1 and run.result_summary["answers_written"] == 2
    assert run.result_summary["batches_total"] == 3
    healthy = _install(monkeypatch, ScriptedModel())

    next_id = await classify_statement(db, seeded.id)

    asked = [description for call in healthy.calls for description in call]
    assert (await _run(db, next_id)).state is RunState.SUCCEEDED
    assert sorted(asked) == sorted(every_row - written), "the next run asks only the rows without an answer"
    assert await _answered_descriptions(db, test_user) == every_row


async def test_AC_extraction_2994_116_a_run_past_its_deadline_keeps_the_batches_that_it_wrote(db, test_user, monkeypatch):
    """AC-extraction.2994.116: Batch 2 hangs past the deadline. The run fails with the timeout code. Batch 1 stays."""
    seeded = await _seed(db, test_user)

    async def hangs_after_batch_1():
        await _wait_until(lambda: _written_rows(db, test_user, 2), seconds=2.5)
        await asyncio.sleep(3600)  # cancelled by the deadline: no real wait

    model = _install(monkeypatch, ScriptedModel(None, hangs_after_batch_1))
    run_id = await classify_run_for(db, seeded.id)

    posted = await asyncio.wait_for(
        _worker(create_session_maker_from_db(db), run_id, deadline_seconds=3.0), timeout=WAIT_SECONDS
    )

    run = await _run(db, run_id)
    assert posted == 0
    assert (run.state, run.error_code) == (RunState.FAILED, "classification_timeout")
    assert await _answered_descriptions(db, test_user) == set(model.calls[0])


# --- A batch write refreshes the heartbeat: a long batch does not get the run reaped ---------------------


class FakeClock:
    def __init__(self) -> None:
        self.seconds = 0.0

    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=self.seconds)


async def test_AC_extraction_2994_96_each_batch_write_refreshes_the_heartbeat_so_a_batch_of_59_seconds_is_never_reaped(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.96: Six batches of 59 s (354 s in all) pass the 300 s threshold. No heartbeat task runs.

    The clock is injected: the model call advances it, and the probe asks the reaper at that time. Without a refresh in
    each batch write, the probe of batch 6 is 354 s after the claim and the reaper fails the run.
    """
    clock = FakeClock()
    monkeypatch.setattr(statement_runs, "_now", clock.now)
    seeded = await _seed(db, test_user, _rows(12))
    run_id = await classify_run_for(db, seeded.id)
    maker = create_session_maker_from_db(db)
    probes: list[list[UUID]] = []

    async def takes_59_seconds():
        clock.seconds += 59
        async with maker() as other_session:
            probes.append(await reap_stale_runs(other_session, now=clock.now()))
            await other_session.commit()

    model = _install(monkeypatch, ScriptedModel(*[takes_59_seconds] * 6))

    await _worker(maker, run_id)

    run = await _run(db, run_id)
    assert len(model.calls) == 6 and clock.seconds == 354
    assert probes == [[]] * 6, "the reaper failed a live run"
    assert run.state is RunState.SUCCEEDED
    assert await _answers(db, test_user) == 12


def test_AC_extraction_2994_96_the_deadline_of_the_run_is_shorter_than_the_stale_threshold():
    """AC-extraction.2994.96: A live run ends at its deadline. The reaper waits longer than that for a heartbeat."""
    assert CLASSIFICATION_PHASE_DEADLINE_SECONDS < statement_runs.DEFAULT_STALE_AFTER.total_seconds()


# --- Two classification paths on the same rows ----------------------------------------------------------


async def test_AC_extraction_2994_119_an_inline_classification_and_a_run_of_the_same_rows_write_one_answer_each(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.119: The inline path commits while the run waits for the model. Neither fails, no row has two answers."""
    seeded = await _seed(db, test_user)
    await _add_coffee_rule(db, test_user)
    gate = asyncio.Event()
    model = _install(monkeypatch, ScriptedModel(gate))
    run_id = await classify_run_for(db, seeded.id)
    maker = create_session_maker_from_db(db)
    worker = asyncio.create_task(_worker(maker, run_id))
    try:
        await asyncio.wait_for(model.reached(0).wait(), timeout=WAIT_SECONDS)
        async with maker() as inline:
            await asyncio.wait_for(
                classify_by_effective_policy(inline, test_user.id, seeded.transactions), timeout=10
            )
            await inline.commit()
    finally:
        gate.set()
    posted = await asyncio.wait_for(worker, timeout=WAIT_SECONDS)

    run = await _run(db, run_id)
    assert posted == 0 and run.state is RunState.SUCCEEDED
    rows = await db.execute(
        select(TransactionClassification.atomic_txn_id, func.count())
        .join(AtomicTransaction, AtomicTransaction.id == TransactionClassification.atomic_txn_id)
        .where(AtomicTransaction.user_id == test_user.id)
        .group_by(TransactionClassification.atomic_txn_id)
    )
    assert sorted(count for _txn, count in rows) == [1, 1, 1, 1, 1], "one answer for each row"


async def test_AC_extraction_2994_119_a_unique_key_collision_counts_as_already_answered(db, test_user, monkeypatch):
    """AC-extraction.2994.119: A writer that skipped the lock took a row. The second pass of the batch skips it."""
    seeded = await _seed(db, test_user, _rows(3))
    _install(monkeypatch, ScriptedModel())
    await classify_by_effective_policy(db, test_user.id, seeded.transactions[:1])
    await db.commit()
    assert await _answers(db, test_user) == 1
    real, reads = transaction_classification._already_classified_ids, []

    async def hides_the_row_from_the_plan_and_the_first_pass(*args, **kwargs):
        reads.append(1)
        return set() if len(reads) <= 2 else await real(*args, **kwargs)

    monkeypatch.setattr(
        transaction_classification, "_already_classified_ids", hides_the_row_from_the_plan_and_the_first_pass
    )
    model = _install(monkeypatch, ScriptedModel())

    run_id = await classify_statement(db, seeded.id)

    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
    assert len(model.calls) == 2
    assert await _answers(db, test_user) == 3


# --- The log lines of the phases and the batches -------------------------------------------------------


def _events(caplog, name: str) -> list[dict]:
    return [r.msg for r in caplog.records if isinstance(r.msg, dict) and r.msg.get("event") == name]


async def test_AC_extraction_2994_120_each_phase_and_each_batch_writes_one_log_line_with_counts_and_no_row_text(
    db, test_user, monkeypatch, caplog
):
    """AC-extraction.2994.120: The lines hold the run id, the policy version, the batch index, counts and ms. No row text."""
    caplog.set_level(logging.DEBUG)
    seeded = await _seed(db, test_user)
    await _add_coffee_rule(db, test_user)
    _install(monkeypatch, ScriptedModel())

    run_id = await classify_statement(db, seeded.id)

    plan, rules = _events(caplog, "statement.classification.plan"), _events(caplog, "statement.classification.rule_answers")
    batches = sorted(_events(caplog, "statement.classification.batch"), key=lambda event: event["batch_index"])
    assert len(plan) == len(rules) == 1 and len(batches) == 2
    assert plan[0]["run_id"] == rules[0]["run_id"] == str(run_id) and plan[0]["rows"] == 5
    assert [(b["batch_index"], b["rows_asked"], b["answers_written"], b["policy_version"]) for b in batches] == [
        (0, 2, 2, 2),
        (1, 2, 2, 2),
    ]
    assert all(isinstance(b["model_ms"], float) and isinstance(b["duration_ms"], float) for b in batches)
    assert all(b["by_disposition"] == {"applied": 2} for b in batches)
    text_of_all_records = "\n".join(f"{r.getMessage()} {r.msg!r}" for r in caplog.records)
    for row in _rows():
        assert row["description"] not in text_of_all_records and str(row["amount"]) not in text_of_all_records


@pytest.mark.parametrize("failure", ["model", "write"])
async def test_AC_extraction_2994_120_a_failed_batch_logs_the_class_of_the_error_and_no_row_text(
    db, test_user, monkeypatch, caplog, failure
):
    """AC-extraction.2994.120: An error text with a description and an amount reaches neither a log line nor the run row."""
    caplog.set_level(logging.DEBUG)
    seeded = await _seed(db, test_user)
    _install(monkeypatch, ScriptedModel(None, RuntimeError(SECRET)) if failure == "model" else ScriptedModel())
    if failure == "write":
        real, writes = transaction_classification._supersede_older_model_rows, []

        async def second_write_fails(db_, user_id, txn_ids, version):
            if txn_ids:
                writes.append(1)
                if len(writes) == 2:
                    raise RuntimeError(SECRET)
            return await real(db_, user_id, txn_ids, version)

        monkeypatch.setattr(transaction_classification, "_supersede_older_model_rows", second_write_fails)

    run = await _run(db, await classify_statement(db, seeded.id))

    text_of_all_records = "\n".join(f"{r.getMessage()} {r.msg!r} {r.exc_text or ''}" for r in caplog.records)
    assert (run.state, run.error_code) == (RunState.FAILED, "classification_failed")
    assert "PAYNOW" not in text_of_all_records and "2500.00" not in text_of_all_records
    assert "PAYNOW" not in str(run.result_summary) and "PAYNOW" not in str(run.error_message)
    assert _events(caplog, "statement.classification.failed")[0]["error_type"] == "RuntimeError"
