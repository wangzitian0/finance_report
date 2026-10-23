"""Classify the transactions of a parsed statement once, before the user approves it (#2637).

Staging ``v0.2.27`` took 26.35 s to approve a statement of 80 rows. Posting the 80 entries took 0.58 s. The rest was
the model call of the classification: nothing classified a statement before the approval, so the first model call
ran inside the approve request.

This pass runs at the end of the ingestion, after the commit that makes the statement ``PARSED``. The user sees
the parsed statement first. The pass is best effort:

* It calls ``classify_by_effective_policy``, the same function that the approval calls. Each row gets the policy
  of its own date. The pass changes no rule of classification.
* A failure or a timeout is logged and counted. The rows stay unclassified, and the approval classifies them as it
  did before this pass existed.
* It takes the lock of the statement (see ``lock_statement_classification``). The approval takes the same lock. The
  approval of a statement that the pass still classifies waits for the pass and then asks the model only for the
  rows without an answer. A pass that finds the lock held leaves the statement to the holder.
* It leaves out what the approval would not classify now: a statement that is not ``PARSED``, a row that a posted
  entry covers, a row whose currency is not resolved (the account of an answer follows the currency), and every
  row when the user turned the model off.
* It writes no rule row. A rule row follows the rules of the moment of the approval, as before.

Manual replay: ``POST /classifications/backfill`` classifies the rows of a user that have no answer. A reparse
runs this pass again.
"""

from __future__ import annotations

import asyncio
import time
from enum import StrEnum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.extraction.base.source_vocabulary import BankStatementStatus
from src.extraction.extension.ai_settings import classification_enabled
from src.extraction.extension.statement_posting import posted_entry_txn_ids
from src.extraction.extension.statement_validation import resolve_statement_transactions
from src.extraction.extension.transaction_classification import (
    CLASSIFICATION_PHASE_DEADLINE_SECONDS,
    ClassificationOutcome,
    classify_by_effective_policy,
    try_lock_statement_classification,
)
from src.extraction.orm.statement_summary import StatementSummary
from src.observability import get_logger, record_statement_classification_outcome, safe_error_message

logger = get_logger(__name__)

#: The outcomes of a pass that need no model call at a later approval.
_NOT_ASKED = frozenset({"already_classified", "rule"})


class StatementClassificationPhase(StrEnum):
    """How one pass after parse ended. The value is the label of the counter."""

    #: Each row that the pass asked the model about has a stored answer.
    CLASSIFIED = "classified"
    #: At least one asked row has no stored answer. The approval asks for it.
    PARTIAL = "partial"
    #: Every row had an answer, or a rule matched it, or no row qualified.
    NOTHING_TO_CLASSIFY = "nothing_to_classify"
    #: The approval, or a second pass, holds the lock of the statement.
    SKIPPED_LOCKED = "skipped_locked"
    #: The statement is gone or is not ``PARSED``, or its rows cannot be resolved.
    SKIPPED_STATE = "skipped_state"
    #: The user turned the model off.
    SKIPPED_DISABLED = "skipped_disabled"
    #: The pass ran past ``CLASSIFICATION_PHASE_DEADLINE_SECONDS`` and wrote nothing.
    TIMED_OUT = "timed_out"
    #: An error ended the pass, and it wrote nothing.
    FAILED = "failed"


async def classify_parsed_statement(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    statement_id: UUID,
    user_id: UUID,
) -> StatementClassificationPhase:
    """Classify the rows of a parsed statement. This call never raises, except for a cancellation."""
    started = time.perf_counter()
    try:
        phase = await asyncio.wait_for(
            _classify(session_maker, statement_id=statement_id, user_id=user_id),
            timeout=CLASSIFICATION_PHASE_DEADLINE_SECONDS,
        )
    except TimeoutError:
        phase = StatementClassificationPhase.TIMED_OUT
        logger.warning(
            "statement.classification.timed_out",
            audit_event="statement.classification.timed_out",
            statement_id=str(statement_id),
            deadline_seconds=CLASSIFICATION_PHASE_DEADLINE_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 - best effort: the approval classifies the rows that have no answer
        phase = StatementClassificationPhase.FAILED
        logger.warning(
            "statement.classification.failed",
            audit_event="statement.classification.failed",
            statement_id=str(statement_id),
            error_type=type(exc).__name__,
            safe_error_message=safe_error_message(str(exc)),
        )
    record_statement_classification_outcome(outcome=phase.value)
    logger.info(
        "statement.classification.finished",
        audit_event="statement.classification.finished",
        statement_id=str(statement_id),
        phase=phase.value,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return phase


async def _classify(
    session_maker: async_sessionmaker[AsyncSession], *, statement_id: UUID, user_id: UUID
) -> StatementClassificationPhase:
    async with session_maker() as session:
        if not await try_lock_statement_classification(session, statement_id):
            return StatementClassificationPhase.SKIPPED_LOCKED
        # The lock came first. A task that held it has committed by now, so these reads see its writes.
        statement = await session.get(StatementSummary, statement_id)
        if statement is None or statement.user_id != user_id or statement.status is not BankStatementStatus.PARSED:
            return StatementClassificationPhase.SKIPPED_STATE
        if not await classification_enabled(session, user_id):
            return StatementClassificationPhase.SKIPPED_DISABLED
        try:
            transactions = await resolve_statement_transactions(session, statement)
        except ValueError:
            # The approval raises the same error and the user sees it there.
            return StatementClassificationPhase.SKIPPED_STATE
        covered = await posted_entry_txn_ids(session, user_id, [txn.id for txn in transactions])
        rows = [txn for txn in transactions if txn.id not in covered and not txn.currency_unresolved]
        if not rows:
            return StatementClassificationPhase.NOTHING_TO_CLASSIFY
        outcomes = await classify_by_effective_policy(session, user_id, rows, apply_rules=False)
        await session.commit()
    return _phase_of(outcomes)


def _phase_of(outcomes: list[ClassificationOutcome]) -> StatementClassificationPhase:
    asked = [outcome for outcome in outcomes if outcome.disposition not in _NOT_ASKED]
    if not asked:
        return StatementClassificationPhase.NOTHING_TO_CLASSIFY
    if any(not outcome.wrote_row for outcome in asked):
        return StatementClassificationPhase.PARTIAL
    return StatementClassificationPhase.CLASSIFIED
