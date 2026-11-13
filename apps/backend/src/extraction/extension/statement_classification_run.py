"""Execute a classify run and auto-approve a candidate in the transaction that ends it (#2994).

The final transaction of an extract run creates the `classify` run (`statement_parsing.py`); the same task claims it
here. While it is active the statement is PARSED and the approve answers 409. The run writes the answers of the rows
without one (`classify_by_effective_policy` with the stored keyword rules). A timeout or an error fails the run, writes
no answer and keeps no row text. A statement that the extract run marked (`AUTO_APPROVE_CANDIDATE`) keeps its run active
until the auto-approve ends it, in one transaction.
"""

from __future__ import annotations

import asyncio
import time
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.extraction.base.source_vocabulary import BankStatementStatus
from src.extraction.extension.ai_settings import classification_enabled
from src.extraction.extension.statement_parsing_supervisor import parsing_heartbeat
from src.extraction.extension.statement_posting import (
    StatementPostingDependencies,
    auto_approve_parsed_candidate,
    posted_entry_txn_ids,
)
from src.extraction.extension.statement_runs import StaleRun, claim_run, fail_run, finish_run
from src.extraction.extension.statement_validation import resolve_statement_transactions
from src.extraction.extension.transaction_classification import (
    CLASSIFICATION_PHASE_DEADLINE_SECONDS,
    ClassificationOutcome,
    classify_by_effective_policy,
    summarize_outcomes,
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
    TIMED_OUT = "timed_out"  # past the deadline: nothing written
    FAILED = "failed"  # an error: nothing written


#: The run error code and message of the two failure outcomes. The message holds no row text.
_FAILURES = {
    ClassifyOutcome.TIMED_OUT: (
        "classification_timeout",
        "The classification ran past its deadline. The rows keep no answer.",
    ),
    ClassifyOutcome.FAILED: ("classification_failed", "The classification failed. The rows keep no answer."),
}


async def execute_classify_run(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    run_id: UUID,
    posting_dependencies: StatementPostingDependencies,
    deadline_seconds: float = CLASSIFICATION_PHASE_DEADLINE_SECONDS,
    heartbeat_interval: float | None = None,
) -> int:
    """Claim and execute one classify run. Return the number of entries that the auto-approve posted.

    This call never raises, except for a cancellation. A run that the worker cannot claim, or that the reaper failed
    while the worker ran, changes nothing and returns 0.
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
        async with parsing_heartbeat(run_id, session_maker, interval_seconds=heartbeat_interval):
            async with deadline:
                # A candidate keeps its run active: the run ends in the transaction of the auto-approve.
                outcome, summary = await _classify_and_commit(
                    session_maker, run_id, statement_id, user_id, finish=not candidate
                )
            if candidate:
                posted = await _approve_and_finish(
                    session_maker, run_id, statement_id, user_id, summary, posting_dependencies
                )
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
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return 0 if outcome in _FAILURES else posted


async def _parent_marked_candidate(session: AsyncSession, parent_run_id: UUID | None) -> bool:
    """Return True when the extract run of this classify run marked its statement as an auto-approve candidate."""
    if parent_run_id is None:
        return False
    summary = await session.scalar(select(StatementRun.result_summary).where(StatementRun.id == parent_run_id))
    return isinstance(summary, dict) and summary.get(AUTO_APPROVE_CANDIDATE) is True


async def _classify_and_commit(
    session_maker: async_sessionmaker[AsyncSession], run_id: UUID, statement_id: UUID, user_id: UUID, *, finish: bool
) -> tuple[ClassifyOutcome, dict]:
    """Commit the answers, and end the run in the same transaction when `finish`. The summary holds counts only."""
    async with session_maker() as session:
        outcome, outcomes = await _classify_rows(session, statement_id, user_id)
        summary = {"outcome": outcome.value, **summarize_outcomes(outcomes)}
        if finish:
            await finish_run(session, run_id, result_summary=summary)
        await session.commit()
    return outcome, summary


async def _classify_rows(
    session: AsyncSession, statement_id: UUID, user_id: UUID
) -> tuple[ClassifyOutcome, list[ClassificationOutcome]]:
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
    enabled = await classification_enabled(session, user_id)
    outcomes = await classify_by_effective_policy(session, user_id, rows, apply_rules=True)
    asked = [outcome for outcome in outcomes if outcome.disposition not in _NOT_ASKED]
    if not enabled:
        return ClassifyOutcome.SKIPPED_DISABLED, outcomes
    if not asked:
        return ClassifyOutcome.NOTHING_TO_CLASSIFY, outcomes
    return (ClassifyOutcome.PARTIAL if any(not o.wrote_row for o in asked) else ClassifyOutcome.CLASSIFIED), outcomes


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
    async with session_maker() as session:
        await finish_run(session, run_id, result_summary=summary)
        await session.commit()
    return 0
