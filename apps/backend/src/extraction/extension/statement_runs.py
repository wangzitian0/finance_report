"""State module of a statement run (#2994).

A run moves from requested to running, then to one terminal state. This module is the only code that
changes the state columns of `statement_runs`. Each change is one conditional `UPDATE ... WHERE state IN
(...)` in `_update_runs`. If the UPDATE matches no row, the run left the expected state, for example because
the reaper failed it. The call then raises `StaleRun` and changes nothing. A partial unique index allows one
active run per statement. No advisory lock and no `SELECT ... FOR UPDATE` guard a run.

Each transition writes one TraceRecord observation in the same transaction. Every function flushes and
never commits. The caller commits right after the call and before any model call. The trace repository
holds an advisory lock on the record lineage until that commit.

A TraceRecord has no field for free text, and the audit contract keeps user text out of its fields. The
requested record therefore pins the hints, the actor and the other inputs with a digest. The digest is the
SHA-256 of their canonical JSON, stored in `evidence_manifest_digest`. The immutable run row keeps the
hints verbatim.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import (
    SqlTraceRecordRepository,
    TraceAuthorityProfile,
    TraceEmitter,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
    canonical_json_digest,
    text_digest,
)
from src.extraction.base.run_vocabulary import (
    ACTIVE_RUN_STATES,
    ERROR_MESSAGE_MAX_LENGTH,
    RunActorKind,
    RunKind,
    RunState,
    RunTrigger,
)
from src.extraction.base.types import RunHints
from src.extraction.orm.statement_run import StatementRun
from src.observability import get_logger

logger = get_logger(__name__)

DEFAULT_STALE_AFTER = timedelta(minutes=5)
HEARTBEAT_LOST = "heartbeat_lost"
_SEQ_ATTEMPTS = 3
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_TRACE_AUTHORITY = TraceAuthorityProfile(
    package="extraction",
    tier="CODE-ONLY",
    proof_kind="exact",
    provenance="deterministic",
    execution_stage="product.runtime",
    assertion_owner_digest=text_digest("extraction:statement_run:v1"),
    producer_version="1",
)
_TRACE_RESULT = {
    RunState.REQUESTED: TraceResult.PASS,
    RunState.RUNNING: TraceResult.PASS,
    RunState.SUCCEEDED: TraceResult.PASS,
    RunState.FAILED: TraceResult.FAIL,
    RunState.CANCELLED: TraceResult.SKIPPED,
}


class ActiveRunExists(RuntimeError):
    """The statement already has a requested or running run."""

    def __init__(self, active_run_id: UUID) -> None:
        super().__init__(f"The statement has an active run: {active_run_id}")
        self.active_run_id = active_run_id


class StaleRun(RuntimeError):
    """The run is not in a state that allows the transition. The call changed nothing."""

    def __init__(self, run_id: UUID, to_state: RunState) -> None:
        super().__init__(f"Run {run_id} cannot change to {to_state.value}: it is not in an accepted state")
        self.run_id = run_id
        self.to_state = to_state


def _now() -> datetime:
    return datetime.now(UTC)


async def _update_runs(db: AsyncSession, *where: ColumnElement[bool], **values: object) -> list[StatementRun]:
    """Run the only UPDATE on statement_runs. The WHERE clause holds the state guard."""
    result = await db.execute(
        update(StatementRun)
        .where(*where)
        .values(**values)
        .returning(StatementRun)
        .execution_options(populate_existing=True, synchronize_session=False)
    )
    return sorted(result.scalars(), key=lambda run: (run.requested_at, str(run.id)))


async def _transition(
    db: AsyncSession, *where: ColumnElement[bool], to_state: RunState, **values: object
) -> list[StatementRun]:
    """Change the state of every run that matches, then write one trace record for each."""
    runs = await _update_runs(db, *where, state=to_state, **values)
    if runs:
        await TraceEmitter(SqlTraceRecordRepository(db)).emit_many([_trace_record(run) for run in runs])
        for run in runs:
            _log_transition(run)
    return runs


def _only(runs: list[StatementRun], run_id: UUID, to_state: RunState) -> StatementRun:
    if not runs:
        raise StaleRun(run_id, to_state)
    return runs[0]


def _occurred_at(run: StatementRun) -> datetime:
    """The time of the transition, as the UPDATE wrote it into the row."""
    moment = {
        RunState.REQUESTED: run.requested_at,
        RunState.RUNNING: run.started_at,
    }.get(run.state, run.finished_at)
    assert moment is not None, f"run {run.id} in state {run.state.value} has no transition time"
    return moment


def _reason_code(run: StatementRun) -> str:
    if run.state is RunState.REQUESTED:
        return f"run_requested.{run.actor_kind.value}.{run.trigger.value}"
    if run.state is RunState.FAILED:
        return f"run_failed.{run.error_code}"
    return f"run_{run.state.value}"


def _manifest(run: StatementRun) -> dict[str, object]:
    """The facts that the evidence digest of the record pins. Free error text is not one of them."""
    if run.state is RunState.REQUESTED:
        return {
            "kind": run.kind.value,
            "actor_kind": run.actor_kind.value,
            "trigger": run.trigger.value,
            "seq": run.seq,
            "hints": run.hints,
            "model": run.model,
            "prompt_template_version": run.prompt_template_version,
            "prompt_digest": run.prompt_digest,
            "parent_run_id": str(run.parent_run_id) if run.parent_run_id is not None else None,
        }
    manifest: dict[str, object] = {"state": run.state.value, "run_id": str(run.id)}
    if run.state is RunState.SUCCEEDED:
        manifest["extraction_result_id"] = str(run.extraction_result_id) if run.extraction_result_id else None
        manifest["result_summary_digest"] = (
            canonical_json_digest(run.result_summary) if run.result_summary is not None else None
        )
    if run.state is RunState.FAILED:
        manifest["error_code"] = run.error_code
        manifest["retryable"] = (run.result_summary or {}).get("retryable")
    return manifest


def _trace_record(run: StatementRun) -> TraceRecord:
    return TraceRecord.observation(
        scope=TraceScope.tenant(run.user_id),
        target=VersionedTraceRef("statement_run", str(run.id), "1"),
        target_class=TraceTargetClass.GENERAL,
        assertion=VersionedTraceRef("statement_run_transition", f"{run.kind.value}.{run.state.value}", "1"),
        authority=_TRACE_AUTHORITY,
        result=_TRACE_RESULT[run.state],
        execution_id=f"statement:{run.statement_id}:run:{run.id}",
        evidence_manifest_digest=canonical_json_digest(_manifest(run)),
        occurred_at=_occurred_at(run),
        score=None,
        reason_code=_reason_code(run),
    )


def _log_transition(run: StatementRun) -> None:
    """Log ids, codes, the hints digest and the keyword count. Hint text never reaches a log."""
    fields: dict[str, object] = {
        "run_id": str(run.id),
        "kind": run.kind.value,
        "state": run.state.value,
        "hints_digest": canonical_json_digest(run.hints),
        "hint_keyword_count": len(run.hints.get("keywords", [])),
    }
    if run.state is RunState.FAILED:
        fields["error_code"] = run.error_code
    logger.info("statement.run.transition", **fields)


async def _next_seq(db: AsyncSession, statement_id: UUID) -> int:
    highest = await db.scalar(
        select(func.coalesce(func.max(StatementRun.seq), 0)).where(StatementRun.statement_id == statement_id)
    )
    return int(highest or 0) + 1


async def get_active_run(db: AsyncSession, statement_id: UUID) -> StatementRun | None:
    """Return the requested or running run of the statement, if one exists."""
    return await db.scalar(
        select(StatementRun)
        .where(StatementRun.statement_id == statement_id, StatementRun.state.in_(ACTIVE_RUN_STATES))
        .execution_options(populate_existing=True)
    )


async def create_run(
    db: AsyncSession,
    *,
    statement_id: UUID,
    user_id: UUID,
    kind: RunKind,
    actor_kind: RunActorKind,
    trigger: RunTrigger,
    hints: RunHints,
    model: str | None = None,
    prompt_template_version: str | None = None,
    prompt_digest: str | None = None,
    parent_run_id: UUID | None = None,
) -> StatementRun:
    """Insert a requested run with the next attempt number.

    The partial unique index rejects a second active run. The function then raises `ActiveRunExists`
    with the id of the active run.
    """
    requested_at = _now()
    last_error: IntegrityError | None = None
    for _attempt in range(_SEQ_ATTEMPTS):
        run = StatementRun(
            id=uuid4(),
            statement_id=statement_id,
            user_id=user_id,
            seq=await _next_seq(db, statement_id),
            kind=kind,
            state=RunState.REQUESTED,
            actor_kind=actor_kind,
            trigger=trigger,
            parent_run_id=parent_run_id,
            hints=hints.model_dump(mode="json"),
            model=model,
            prompt_template_version=prompt_template_version,
            prompt_digest=prompt_digest,
            requested_at=requested_at,
        )
        try:
            async with db.begin_nested():
                db.add(run)
                await db.flush()
        except IntegrityError as error:
            active = await get_active_run(db, statement_id)
            if active is not None:
                raise ActiveRunExists(active.id) from None
            # A run that finished while this call ran took the number. Take the next number.
            last_error = error
            continue
        await TraceEmitter(SqlTraceRecordRepository(db)).emit_many([_trace_record(run)])
        _log_transition(run)
        return run
    assert last_error is not None
    last_error.hide_parameters = True  # The INSERT parameters hold the hints.
    raise last_error


async def claim_run(db: AsyncSession, run_id: UUID) -> StatementRun:
    """Move a requested run to running. Of two concurrent callers, one wins and one gets `StaleRun`."""
    now = _now()
    runs = await _transition(
        db,
        StatementRun.id == run_id,
        StatementRun.state == RunState.REQUESTED,
        to_state=RunState.RUNNING,
        started_at=now,
        heartbeat_at=now,
    )
    return _only(runs, run_id, RunState.RUNNING)


async def heartbeat_run(db: AsyncSession, run_id: UUID) -> bool:
    """Show that the worker lives. Return False when the run is no longer running."""
    runs = await _update_runs(
        db, StatementRun.id == run_id, StatementRun.state == RunState.RUNNING, heartbeat_at=_now()
    )
    return bool(runs)


async def finish_run(
    db: AsyncSession,
    run_id: UUID,
    *,
    extraction_result_id: UUID | None = None,
    result_summary: dict | None = None,
) -> StatementRun:
    """Move a running run to succeeded. A finish after the reaper failed the run raises `StaleRun`."""
    runs = await _transition(
        db,
        StatementRun.id == run_id,
        StatementRun.state == RunState.RUNNING,
        to_state=RunState.SUCCEEDED,
        finished_at=_now(),
        extraction_result_id=extraction_result_id,
        result_summary=result_summary,
    )
    return _only(runs, run_id, RunState.SUCCEEDED)


async def fail_run(
    db: AsyncSession,
    run_id: UUID,
    *,
    error_code: str,
    error_message: str,
    retryable: bool = False,
) -> StatementRun:
    """Move a requested or running run to failed.

    `error_code` is a short machine code. The caller redacts `error_message`. The flag `retryable` goes
    into `result_summary`, so a later step can find the failed runs that it may retry.
    """
    if _ERROR_CODE.fullmatch(error_code) is None:
        raise ValueError("error_code is 1 to 64 characters: a lowercase letter, then lowercase letters, digits or _")
    if len(error_message) > ERROR_MESSAGE_MAX_LENGTH:
        raise ValueError(f"error_message has at most {ERROR_MESSAGE_MAX_LENGTH} characters")
    runs = await _transition(
        db,
        StatementRun.id == run_id,
        StatementRun.state.in_(ACTIVE_RUN_STATES),
        to_state=RunState.FAILED,
        finished_at=_now(),
        error_code=error_code,
        error_message=error_message,
        result_summary={"retryable": retryable},
    )
    return _only(runs, run_id, RunState.FAILED)


async def reap_stale_runs(
    db: AsyncSession,
    *,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    now: datetime | None = None,
) -> list[UUID]:
    """Fail every running run whose heartbeat is older than `stale_after`. Return the failed run ids."""
    moment = now or _now()
    runs = await _transition(
        db,
        StatementRun.state == RunState.RUNNING,
        StatementRun.heartbeat_at < moment - stale_after,
        to_state=RunState.FAILED,
        finished_at=moment,
        error_code=HEARTBEAT_LOST,
        error_message=f"The worker sent no heartbeat for more than {int(stale_after.total_seconds())} seconds.",
        result_summary={"retryable": True},
    )
    return [run.id for run in runs]


__all__ = [
    "ActiveRunExists",
    "StaleRun",
    "claim_run",
    "create_run",
    "fail_run",
    "finish_run",
    "get_active_run",
    "heartbeat_run",
    "reap_stale_runs",
]
