"""AC-audit.trace-record.6: public current-authority read projection."""

from __future__ import annotations

from sqlalchemy import select

from src.audit import (
    SqlTraceRecordRepository,
    TraceDecisionPolicyRegistry,
    TraceRecord,
    current_authoritative_trace_decision_projection,
)

from .conftest import decision_policy, observation


async def test_AC_audit_trace_record_6_current_projection_matches_repository_current_ancestry(db) -> None:
    """A superseded parent removes its descendant from the public authority read."""
    policy = decision_policy()
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,)))
    parent = observation()
    await repository.append(parent)
    decision = TraceRecord.decision(
        scope=parent.scope,
        target=parent.target,
        policy=policy,
        execution_id=parent.execution_id,
        occurred_at=parent.occurred_at,
        parents=(parent,),
    )
    await repository.append(decision)

    projection = current_authoritative_trace_decision_projection(parent.scope).subquery()
    current_ids = set((await db.execute(select(projection.c.decision_id))).scalars())
    assert decision.record_id in current_ids

    await repository.append(
        observation(
            scope=parent.scope,
            target_version="v2",
            assertion_version="v2",
            execution_id="parent-correction",
            supersedes_id=parent.record_id,
        )
    )
    current_ids = set((await db.execute(select(projection.c.decision_id))).scalars())
    assert decision.record_id not in current_ids
