from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.audit import (
    SqlTraceRecordRepository,
    TraceDecisionPolicyRegistry,
    current_authoritative_trace_decisions,
    shared_current_authority,
)
from tests.audit.trace.conftest import decision as _dec, decision_policy, observation


async def test_AC_audit_trace_record_8_shared_block_reads_projection_once_and_invalidates_on_write(
    db, db_engine
) -> None:
    repository, parent = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((decision_policy(),))), observation()
    await repository.append(parent)
    dec = _dec([parent])
    await repository.append(dec)
    await db.commit()
    direct = await current_authoritative_trace_decisions(db, parent.scope, {dec.record_id, parent.record_id})
    assert set(direct) == {dec.record_id} and direct[dec.record_id].target_id == parent.target.id

    stmts: list[str] = []
    record = lambda _c, _cur, stmt, *_a: stmts.append(stmt) if "invalid_trace_records" in stmt else None
    event.listen(db_engine.sync_engine, "before_cursor_execute", record)
    try:
        async with shared_current_authority(db, parent.scope):
            assert len(stmts) == 1
            first = await current_authoritative_trace_decisions(db, parent.scope, {dec.record_id, parent.record_id})
            second = await current_authoritative_trace_decisions(db, parent.scope, [dec.record_id])
            async with shared_current_authority(db, parent.scope):
                nested = await current_authoritative_trace_decisions(db, parent.scope, [dec.record_id])
            assert len(stmts) == 1
            async with async_sessionmaker(db_engine, expire_on_commit=False)() as other:
                other_read = await current_authoritative_trace_decisions(other, parent.scope, [dec.record_id])
            assert len(stmts) == 2
        after = await current_authoritative_trace_decisions(db, parent.scope, [dec.record_id])
        assert len(stmts) == 3

        stmts.clear()
        async with shared_current_authority(db, parent.scope):
            assert set(await current_authoritative_trace_decisions(db, parent.scope, [dec.record_id])) == {
                dec.record_id
            }
            await repository.append(
                observation(
                    scope=parent.scope,
                    target_version="v2",
                    assertion_version="v2",
                    execution_id="parent-correction",
                    supersedes_id=parent.record_id,
                )
            )
            reads_before = len(stmts)
            assert (await current_authoritative_trace_decisions(db, parent.scope, [dec.record_id]), len(stmts)) == (
                {},
                reads_before + 1,
            )
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", record)

    assert all(
        set(res) == {dec.record_id} and tuple(res[dec.record_id]) == tuple(direct[dec.record_id])
        for res in (first, second, nested, other_read, after)
    )
    assert await current_authoritative_trace_decisions(db, parent.scope, []) == {}
