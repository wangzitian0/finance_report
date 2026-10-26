"""SQL read projection over the canonical TraceRecord decision graph."""

from __future__ import annotations

from collections.abc import AsyncIterator, Collection, Mapping
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import Row, Select, event, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session

from src.audit.base.trace import TraceRecordType, TraceResult, TraceScope, TraceTargetClass
from src.audit.orm.trace_record import TraceRecordParentRow, TraceRecordRow

# ``Session.info`` key of the shared current-authority reads of a session, keyed by scope.
_SHARED_READS_KEY = "audit.shared_current_authority"
_TRACE_TABLES = (TraceRecordRow, TraceRecordParentRow)


def trace_decision_projection(scope: TraceScope) -> Select:
    """Select the common identity fields of every decision in one scope.

    Callers join this projection by ``decision_id``. TraceRecord remains the
    only owner of target, policy, and CODE/LLM authority metadata.
    """
    return (
        select(
            TraceRecordRow.id.label("decision_id"),
            TraceRecordRow.target_kind,
            TraceRecordRow.target_id,
            TraceRecordRow.target_version,
            TraceRecordRow.assertion_kind,
            TraceRecordRow.assertion_id,
            TraceRecordRow.assertion_version,
            TraceRecordRow.authority_tier,
        )
        .where(TraceRecordRow.scope_kind == scope.kind)
        .where(TraceRecordRow.scope_id == scope.id)
        .where(TraceRecordRow.record_type == TraceRecordType.DECISION)
    )


def current_authoritative_trace_decision_projection(scope: TraceScope) -> Select:
    """Select authoritative decisions whose complete causal graph is current.

    Superseding any record invalidates every descendant decision. The recursive
    CTE preserves the same fail-closed semantics as ``current_decision`` while
    remaining composable in package-owned bulk queries.
    """
    superseded = (
        select(TraceRecordRow.supersedes_id.label("record_id"))
        .where(TraceRecordRow.scope_kind == scope.kind)
        .where(TraceRecordRow.scope_id == scope.id)
        .where(TraceRecordRow.supersedes_id.is_not(None))
        .cte("invalid_trace_records", recursive=True)
    )
    invalid = superseded.alias("invalid_parent")
    superseded = superseded.union(
        select(TraceRecordParentRow.record_id)
        .join(invalid, TraceRecordParentRow.parent_id == invalid.c.record_id)
        .where(TraceRecordParentRow.scope_kind == scope.kind)
        .where(TraceRecordParentRow.scope_id == scope.id)
    )
    return (
        trace_decision_projection(scope)
        .where(TraceRecordRow.result == TraceResult.AUTHORITATIVE)
        .where(TraceRecordRow.target_class == TraceTargetClass.FINANCIAL)
        .where(~exists(select(1).select_from(superseded).where(superseded.c.record_id == TraceRecordRow.id)))
    )


def _shared_reads(db: AsyncSession) -> dict[tuple[str, str], dict[UUID, Row[Any]]]:
    return db.info.setdefault(_SHARED_READS_KEY, {})


async def current_authoritative_trace_decisions(
    db: AsyncSession,
    scope: TraceScope,
    decision_ids: Collection[UUID],
) -> Mapping[UUID, Row[Any]]:
    """Return the current authoritative decisions among ``decision_ids``, keyed by decision id.

    Each row has the columns of ``trace_decision_projection``. An id that is not a current
    authoritative financial decision of ``scope`` is not in the result. In a
    ``shared_current_authority`` block of the same session and scope, the result comes from
    the one projection read of the block. Otherwise one statement reads only these ids.
    """
    wanted = set(decision_ids)
    if not wanted:
        return {}
    shared = _shared_reads(db).get((scope.kind, scope.id))
    if shared is not None:
        return {decision_id: shared[decision_id] for decision_id in wanted if decision_id in shared}
    projection = current_authoritative_trace_decision_projection(scope).subquery("current_authority_decisions")
    rows = await db.execute(select(projection).where(projection.c.decision_id.in_(wanted)))
    return {row.decision_id: row for row in rows}


@asynccontextmanager
async def shared_current_authority(db: AsyncSession, scope: TraceScope) -> AsyncIterator[None]:
    """Read the current-authority projection of ``scope`` once for a block of authority reads.

    In the block, ``current_authoritative_trace_decisions`` on the same session and scope
    answers from this one read (#2602). A TraceRecord write on the session in the block
    removes the read, so the next call queries the projection again: a decision that the
    block supersedes is never reported as current. A nested block reuses the outer read.
    """
    shared = _shared_reads(db)
    key = (scope.kind, scope.id)
    if key in shared:
        yield
        return
    projection = current_authoritative_trace_decision_projection(scope).subquery("current_authority_decisions")
    rows = await db.execute(select(projection))
    shared[key] = {row.decision_id: row for row in rows}

    def _drop_on_flushed_trace_write(session: Session, _flush_context: Any, _instances: Any) -> None:
        if any(isinstance(item, _TRACE_TABLES) for item in (*session.new, *session.dirty, *session.deleted)):
            shared.pop(key, None)

    def _drop_on_trace_statement(state: ORMExecuteState) -> None:
        if (state.is_insert or state.is_update or state.is_delete) and (
            state.bind_mapper is not None and state.bind_mapper.class_ in _TRACE_TABLES
        ):
            shared.pop(key, None)

    session = db.sync_session
    event.listen(session, "before_flush", _drop_on_flushed_trace_write)
    event.listen(session, "do_orm_execute", _drop_on_trace_statement)
    try:
        yield
    finally:
        event.remove(session, "do_orm_execute", _drop_on_trace_statement)
        event.remove(session, "before_flush", _drop_on_flushed_trace_write)
        shared.pop(key, None)
