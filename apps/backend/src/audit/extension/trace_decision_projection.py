"""SQL read projection over the canonical TraceRecord decision graph."""

from __future__ import annotations

from sqlalchemy import Select, exists, select

from src.audit.base.trace import TraceRecordType, TraceResult, TraceScope, TraceTargetClass
from src.audit.orm.trace_record import TraceRecordParentRow, TraceRecordRow


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
