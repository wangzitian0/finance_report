"""AC-audit.trace-record.8: one read of the current-authority projection serves a block of authority reads (#2602)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.audit import (
    SqlTraceRecordRepository,
    TraceDecisionPolicyRegistry,
    TraceRecord,
    current_authoritative_trace_decisions,
    shared_current_authority,
)

from .conftest import decision_policy, observation

PROJECTION_MARKER = "invalid_trace_records"


@contextmanager
def _projection_statements(db_engine) -> Iterator[list[str]]:
    """Collect the current-authority projection statements of the block."""
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if PROJECTION_MARKER in statement:
            statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _record)


async def _decision_with_parent(repository: SqlTraceRecordRepository) -> tuple[TraceRecord, TraceRecord]:
    policy = decision_policy()
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
    return parent, decision


async def test_AC_audit_trace_record_8_shared_block_reads_the_projection_once(db, db_engine) -> None:
    """AC-audit.trace-record.8: inside ``shared_current_authority``, each read of the same session
    and scope uses the one projection read of the block. The result equals a direct read. After
    the block, and on another session, a read queries the projection again."""
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((decision_policy(),)))
    parent, decision = await _decision_with_parent(repository)
    await db.commit()
    missing = parent.record_id  # an observation is not a decision

    direct = await current_authoritative_trace_decisions(db, parent.scope, {decision.record_id, missing})
    assert set(direct) == {decision.record_id}
    assert direct[decision.record_id].target_id == parent.target.id

    with _projection_statements(db_engine) as statements:
        async with shared_current_authority(db, parent.scope):
            assert len(statements) == 1
            first = await current_authoritative_trace_decisions(db, parent.scope, {decision.record_id, missing})
            second = await current_authoritative_trace_decisions(db, parent.scope, [decision.record_id])
            # A nested block reuses the outer read.
            async with shared_current_authority(db, parent.scope):
                nested = await current_authoritative_trace_decisions(db, parent.scope, [decision.record_id])
            assert len(statements) == 1
            async with async_sessionmaker(db_engine, expire_on_commit=False)() as other:
                other_read = await current_authoritative_trace_decisions(other, parent.scope, [decision.record_id])
            assert len(statements) == 2
        after = await current_authoritative_trace_decisions(db, parent.scope, [decision.record_id])
        assert len(statements) == 3

    for result in (first, second, nested, other_read, after):
        assert set(result) == {decision.record_id}
        assert tuple(result[decision.record_id]) == tuple(direct[decision.record_id])
    assert await current_authoritative_trace_decisions(db, parent.scope, []) == {}


async def test_AC_audit_trace_record_8_trace_write_inside_the_block_drops_the_shared_read(db, db_engine) -> None:
    """AC-audit.trace-record.8: a TraceRecord write inside the block ends the reuse of the shared read.
    A superseded parent then removes its decision from the next read, as without the block."""
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((decision_policy(),)))
    parent, decision = await _decision_with_parent(repository)
    await db.commit()

    with _projection_statements(db_engine) as statements:
        async with shared_current_authority(db, parent.scope):
            before = await current_authoritative_trace_decisions(db, parent.scope, [decision.record_id])
            assert set(before) == {decision.record_id}
            await repository.append(
                observation(
                    scope=parent.scope,
                    target_version="v2",
                    assertion_version="v2",
                    execution_id="parent-correction",
                    supersedes_id=parent.record_id,
                )
            )
            reads_before_write = len(statements)
            after = await current_authoritative_trace_decisions(db, parent.scope, [decision.record_id])
            assert len(statements) == reads_before_write + 1
    assert after == {}
