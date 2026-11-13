"""Execute a classify run and auto-approve a candidate in the transaction that ends it (#2994, #3028).

The final transaction of an extract run creates the `classify` run (`statement_parsing.py`); the same task claims it
here. While it is active the statement is PARSED and the approve answers 409. The run works in short phases, each in its
own session that commits and closes: the plan (reads only), the keyword-rule answers, one write for each batch of model
answers, and the finish. The model call has no session. A timeout, an error or the reaper fails the run and keeps the
batches already written; the next run asks only the rows without an answer. A statement that the extract run marked
(`AUTO_APPROVE_CANDIDATE`) keeps its run active until the auto-approve ends it, in one transaction.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.extraction.base.run_vocabulary import RunState
from src.extraction.base.source_vocabulary import BankStatementStatus
from src.extraction.extension.statement_posting import (
    StatementPostingDependencies,
    auto_approve_parsed_candidate,
    posted_entry_txn_ids,
)
from src.extraction.extension.statement_runs import StaleRun, claim_run, fail_run, finish_run, heartbeat_run
from src.extraction.extension.statement_validation import resolve_statement_transactions
from src.extraction.extension.transaction_classification import (
    CLASSIFICATION_PHASE_DEADLINE_SECONDS,
    ClassificationOutcome,
    ClassificationPlan,
    ask_model,
    batch_slots,
    model_batches,
    plan_classification,
    policy_buckets,
    summarize_outcomes,
    write_answers,
    write_before_model,
)
from src.extraction.orm.statement_run import StatementRun
from src.extraction.orm.statement_summary import StatementSummary
from src.observability import get_logger, record_statement_classification_outcome

logger = get_logger(__name__)

#: The key in the `result_summary` of an extract run: the parse marked the statement as an auto-approve candidate.
AUTO_APPROVE_CANDIDATE = "auto_approve_candidate"
_NOT_ASKED = frozenset({"already_classified", "rule"})


class ClassifyOutcome(StrEnum):
    """How a run ended: the label of the counter and the `outcome` of the summary."""

    CLASSIFIED = "classified"  # each asked row has a stored answer
    PARTIAL = "partial"  # an asked row has no answer: the approve sends it to the economic review
    NOTHING_TO_CLASSIFY = "nothing_to_classify"  # every row had an answer or a rule, or no row qualified
    SKIPPED_STATE = "skipped_state"  # the statement is gone, not PARSED, or its rows cannot be resolved
    SKIPPED_DISABLED = "skipped_disabled"  # the user turned the model off: keyword rules still answered
    TIMED_OUT = "timed_out"  # past the deadline: the batches written stay
    FAILED = "failed"  # an error: the batches written stay


#: The run error code and message of the two failure outcomes. The message holds no row text, and it does not say
#: that the rows have no answer: a failure after a batch committed leaves its answers in place.
_FAILURES = {
    ClassifyOutcome.TIMED_OUT: ("classification_timeout", "The classification ran past its deadline."),
    ClassifyOutcome.FAILED: ("classification_failed", "The classification failed."),
}


async def execute_classify_run(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    run_id: UUID,
    posting_dependencies: StatementPostingDependencies,
    deadline_seconds: float = CLASSIFICATION_PHASE_DEADLINE_SECONDS,
) -> int:
    """Claim and execute one classify run. Return the number of entries that the auto-approve posted.

    This call never raises, except for a cancellation. A run that the worker cannot claim, or that the reaper failed
    while the worker ran, changes nothing more and returns 0. No heartbeat task runs: each write of the run refreshes
    `heartbeat_at`, and the deadline is shorter than the stale threshold of the reaper.
    """
    started = time.perf_counter()
    try:
        async with session_maker() as session:
            run = await claim_run(session, run_id)
            statement_id, user_id = run.statement_id, run.user_id
            candidate = await _parent_marked_candidate(session, run.parent_run_id)
            await session.commit()
    except StaleRun:
        logger.warning("statement.classification.claim_stale", run_id=str(run_id))
        return 0
    except Exception as exc:  # noqa: BLE001 - an error of this code must not leave the run requested for 5 minutes
        logger.warning("statement.classification.claim_failed", run_id=str(run_id), error_type=type(exc).__name__)
        await _fail(session_maker, run_id, ClassifyOutcome.FAILED)
        return 0

    posted = 0
    deadline = asyncio.timeout(deadline_seconds)
    try:
        async with deadline:
            outcome, summary = await _classify_in_phases(session_maker, run_id, statement_id, user_id)
        # A candidate keeps its run active: the run ends in the transaction of the auto-approve.
        if candidate:
            posted = await _approve_and_finish(
                session_maker, run_id, statement_id, user_id, summary, posting_dependencies
            )
        else:
            await _finish(session_maker, run_id, summary)
    except StaleRun:
        logger.warning("statement.classification.run_stale", run_id=str(run_id), statement_id=str(statement_id))
        return 0
    except Exception as exc:  # noqa: BLE001 - the statement keeps its rows, and the approve sends them to review
        # A TimeoutError of the driver is a failure, not the deadline of the run. The text of an error can hold row
        # data or driver detail: the log carries the class only.
        timed_out = isinstance(exc, TimeoutError) and deadline.expired()
        outcome = ClassifyOutcome.TIMED_OUT if timed_out else ClassifyOutcome.FAILED
        logger.warning(
            "statement.classification.failed",
            audit_event="statement.classification.failed",
            statement_id=str(statement_id),
            run_id=str(run_id),
            outcome=outcome.value,
            error_type=type(exc).__name__,
        )
        if not await _fail(session_maker, run_id, outcome):
            return 0
    record_statement_classification_outcome(outcome=outcome.value)
    logger.info(
        "statement.classification.finished",
        audit_event="statement.classification.finished",
        statement_id=str(statement_id),
        run_id=str(run_id),
        phase=outcome.value,
        duration_ms=_ms(started),
    )
    return 0 if outcome in _FAILURES else posted


async def _parent_marked_candidate(session: AsyncSession, parent_run_id: UUID | None) -> bool:
    """Return True when the extract run of this classify run marked its statement as an auto-approve candidate."""
    if parent_run_id is None:
        return False
    summary = await session.scalar(select(StatementRun.result_summary).where(StatementRun.id == parent_run_id))
    return isinstance(summary, dict) and summary.get(AUTO_APPROVE_CANDIDATE) is True


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _log(event: str, run_id: UUID, started: float, **fields: object) -> None:
    """One structured line for a phase or a batch: ids, counts and milliseconds, never row text."""
    logger.info(f"statement.classification.{event}", run_id=str(run_id), duration_ms=_ms(started), **fields)


async def _beat(session: AsyncSession, run_id: UUID, progress: dict | None = None) -> None:
    """Refresh the heartbeat and store the progress. A run that is no longer running raises StaleRun: nothing is written."""
    if not await heartbeat_run(session, run_id, result_summary=progress):
        raise StaleRun(run_id, RunState.RUNNING)


async def _plan(
    session: AsyncSession, statement_id: UUID, user_id: UUID
) -> tuple[ClassifyOutcome | None, list[ClassificationPlan]]:
    """Phase a, reads only: the plan of each policy bucket. The outcome is set when there is nothing to plan."""
    statement = await session.get(StatementSummary, statement_id)
    if statement is None or statement.user_id != user_id or statement.status is not BankStatementStatus.PARSED:
        return ClassifyOutcome.SKIPPED_STATE, []
    try:
        transactions = await resolve_statement_transactions(session, statement)
    except ValueError:  # the approval raises the same error, and the user sees it there
        return ClassifyOutcome.SKIPPED_STATE, []
    covered = await posted_entry_txn_ids(session, user_id, [txn.id for txn in transactions])
    # A row with an unresolved currency waits: the account of an answer follows the currency.
    rows = [txn for txn in transactions if txn.id not in covered and not txn.currency_unresolved]
    if not rows:
        return ClassifyOutcome.NOTHING_TO_CLASSIFY, []
    buckets = await policy_buckets(session, user_id, rows, tolerate_pre_policy=True)
    return None, [await plan_classification(session, user_id, bucket, policy) for policy, bucket in buckets]


async def _classify_in_phases(
    session_maker: async_sessionmaker[AsyncSession], run_id: UUID, statement_id: UUID, user_id: UUID
) -> tuple[ClassifyOutcome, dict]:
    """Run the phases. Return the outcome and the summary, which holds counts only. The run itself is still running."""
    started = time.perf_counter()
    async with session_maker() as session:
        skipped, plans = await _plan(session, statement_id, user_id)
    batches = [
        (plan, batch) for plan in plans if plan.policy is not None for batch in model_batches(plan.to_propose, plan.policy)
    ]
    _log(
        "plan",
        run_id,
        started,
        rows=sum(len(plan.rows) for plan in plans),
        rows_to_ask=sum(len(plan.to_propose) for plan in plans),
        batches=len(batches),
    )
    progress = {"batches_done": 0, "batches_total": len(batches), "answers_written": 0}
    started = time.perf_counter()
    async with session_maker() as session:  # phase b: the answers of the keyword rules, committed before any model call
        await _beat(session, run_id, progress)
        for plan in plans:
            await write_before_model(session, plan)
        await session.commit()
    outcomes = [outcome for plan in plans for outcome in plan.base_outcomes()]
    _log("rule_answers", run_id, started, rule_answers=sum(o.disposition == "rule" for o in outcomes))

    slots = batch_slots()

    async def ask(index: int, plan: ClassificationPlan, batch):
        async with slots:
            began = time.perf_counter()
            return index, plan, batch, await ask_model(user_id, batch, plan.policy), _ms(began)

    tasks = [asyncio.ensure_future(ask(index, plan, batch)) for index, (plan, batch) in enumerate(batches)]
    try:
        for finished in asyncio.as_completed(tasks):  # phase c: write each batch when its answer arrives
            index, plan, batch, proposals, model_ms = await finished
            started = time.perf_counter()
            written = await _write_batch(session_maker, run_id, plan, batch, proposals, progress)
            outcomes += written
            _log(
                "batch",
                run_id,
                started,
                policy_version=plan.version,
                batch_index=index,
                rows_asked=len(batch),
                answers_written=sum(o.wrote_row for o in written),
                by_disposition=dict(Counter(o.disposition for o in written)),
                model_ms=model_ms,
            )
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    asked = [outcome for outcome in outcomes if outcome.disposition not in _NOT_ASKED]
    if skipped is not None:
        outcome = skipped
    elif plans and plans[0].policy is None:
        outcome = ClassifyOutcome.SKIPPED_DISABLED
    elif not asked:
        outcome = ClassifyOutcome.NOTHING_TO_CLASSIFY
    else:
        outcome = ClassifyOutcome.PARTIAL if any(not o.wrote_row for o in asked) else ClassifyOutcome.CLASSIFIED
    return outcome, {"outcome": outcome.value, **summarize_outcomes(outcomes), **progress}


async def _write_batch(
    session_maker: async_sessionmaker[AsyncSession],
    run_id: UUID,
    plan: ClassificationPlan,
    batch,
    proposals,
    progress: dict,
) -> list[ClassificationOutcome]:
    """Write one batch in one short transaction. Lock order: the run row (StaleRun if reaped), then `write_answers`.

    A unique-key collision means that a writer took a row without the policy-rule lock: the second pass skips the row.
    """
    retried = False
    while True:
        try:
            async with session_maker() as session:
                await _beat(session, run_id)
                written = await write_answers(session, plan, batch, proposals)
                done = {
                    **progress,
                    "batches_done": progress["batches_done"] + 1,
                    "answers_written": progress["answers_written"] + sum(outcome.wrote_row for outcome in written),
                }
                await _beat(session, run_id, done)
                await session.commit()
            progress.update(done)
            return written
        except IntegrityError:
            if retried:
                raise
            retried = True


async def _finish(session_maker: async_sessionmaker[AsyncSession], run_id: UUID, summary: dict) -> None:
    async with session_maker() as session:
        await finish_run(session, run_id, result_summary=summary)
        await session.commit()


async def _fail(session_maker: async_sessionmaker[AsyncSession], run_id: UUID, outcome: ClassifyOutcome) -> bool:
    """End the run as failed. Return False when the run already left the active states or the write failed."""
    code, message = _FAILURES[outcome]
    try:
        async with session_maker() as session:
            await fail_run(session, run_id, error_code=code, error_message=message)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 - a StaleRun means the reaper failed the run; the reaper fails a run that stays active
        logger.warning("statement.classification.fail_not_written", run_id=str(run_id), error_type=type(exc).__name__)
        return False
    return True


async def _approve_and_finish(
    session_maker: async_sessionmaker[AsyncSession],
    run_id: UUID,
    statement_id: UUID,
    user_id: UUID,
    summary: dict,
    posting_dependencies: StatementPostingDependencies,
) -> int:
    """Approve a marked statement and end the run in one transaction, so no moment shows PARSED without an active run.

    If the approve fails with an error, the statement stays PARSED and the run ends alone.
    """
    try:
        async with session_maker() as session:
            posted = await auto_approve_parsed_candidate(
                session, statement_id, user_id, dependencies=posting_dependencies, ignore_run_id=run_id
            )
            await finish_run(session, run_id, result_summary=summary)
            await session.commit()
        return posted
    except StaleRun:
        raise
    except Exception as exc:  # noqa: BLE001 - the statement stays PARSED, and the user approves it
        logger.warning("statement.auto_approve.failed", statement_id=str(statement_id), error_type=type(exc).__name__)
    await _finish(session_maker, run_id, summary)
    return 0
