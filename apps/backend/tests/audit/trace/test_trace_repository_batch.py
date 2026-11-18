from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError

from src.audit import (
    SqlTraceRecordRepository,
    TraceDecisionPolicyRegistry,
    TraceEmitter,
    TraceRecord,
    TraceRecordPersistenceError,
    TraceScope,
)
from src.audit.orm import TraceRecordParentRow, TraceRecordRow
from tests.audit.trace.conftest import SqlStatements, decision as _dec, decision_policy, observation

pytestmark = pytest.mark.asyncio


def _causal_set(scope: TraceScope, count: int, *, policy) -> list[TraceRecord]:
    records: list[TraceRecord] = []
    for index in range(count):
        parent = observation(scope=scope, target_id=f"subject-{index}")
        records.extend((parent, _dec([parent], policy=policy)))
    return records


async def _persisted(db, scope: TraceScope) -> tuple[list[dict], list[tuple]]:
    rows = (await db.execute(select(TraceRecordRow).where(TraceRecordRow.scope_id == scope.id))).scalars().all()
    parents = (await db.execute(select(TraceRecordParentRow).where(TraceRecordParentRow.scope_id == scope.id))).scalars()
    return (
        sorted(({c.name: getattr(row, c.name) for c in TraceRecordRow.__table__.columns} for row in rows), key=lambda item: str(item["id"])),
        sorted(((link.record_id, link.parent_id) for link in parents)),
    )


async def test_AC_audit_trace_record_9_batch_parity_idempotence_and_statement_budget(db) -> None:
    policy = decision_policy()
    registry = TraceDecisionPolicyRegistry((policy,))
    scope = TraceScope.tenant(uuid4())
    records = _causal_set(scope, 6, policy=policy)
    nested = await db.begin_nested()
    for record in records:
        await SqlTraceRecordRepository(db, registry).append(record)
    sequential = await _persisted(db, scope)
    await nested.rollback()
    assert await _persisted(db, scope) == ([], [])

    emitted = await SqlTraceRecordRepository(db, registry).append_many(records)
    batch = await _persisted(db, scope)
    db.info.clear()
    again = await SqlTraceRecordRepository(db, registry).append_many([*records, records[0]])
    assert (emitted, len(batch[0]), len(batch[1]), batch, again, await _persisted(db, scope)) == (
        tuple(records), 12, 6, sequential, (*records, records[0]), batch,
    )

    small_scope, large_scope, seq_scope = (TraceScope.tenant(uuid4()) for _ in range(3))
    with SqlStatements(db) as small:
        await SqlTraceRecordRepository(db, registry).append_many(_causal_set(small_scope, 2, policy=policy))
    with SqlStatements(db) as large:
        await SqlTraceRecordRepository(db, registry).append_many(_causal_set(large_scope, 30, policy=policy))
    with SqlStatements(db) as seq:
        repo = SqlTraceRecordRepository(db, registry)
        for record in _causal_set(seq_scope, 30, policy=policy):
            await repo.append(record)
    assert len(large.texts) == len(small.texts) <= 6 and len(seq.texts) >= 10 * len(large.texts)


async def test_AC_audit_trace_record_9_batch_locks_and_fallback_paths(db) -> None:
    policy = decision_policy()
    registry = TraceDecisionPolicyRegistry((policy,))
    repository = SqlTraceRecordRepository(db, registry)
    records = _causal_set(TraceScope.tenant(uuid4()), 6, policy=policy)
    captured: list[tuple[str, tuple]] = []
    engine = db.bind.sync_engine
    capture = lambda _c, _cur, stmt, params, *_a: captured.append((stmt, params))
    event.listen(engine, "before_cursor_execute", capture)
    try:
        await repository.append_many(records)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    locks = [i for i, (t, _) in enumerate(captured) if "pg_advisory_xact_lock" in t]
    reads = [i for i, (t, _) in enumerate(captured) if t.startswith("SELECT trace_records")]
    keys = captured[locks[0]][1][0]
    assert len(locks) == 1 and reads and locks[0] < min(reads)
    assert len(keys) == len({r.lineage for r in records}) == 12 and list(keys) == sorted(keys)

    scope = TraceScope.tenant(uuid4())
    original = observation(scope=scope)
    await repository.append_many([original])
    correction = observation(scope=scope, target_version="v2", assertion_version="v2", supersedes_id=original.record_id, score="0.5")
    pol_v2 = decision_policy(assertion_version="v2")
    decision = TraceRecord.decision(scope=scope, target=correction.target, policy=pol_v2, execution_id=correction.execution_id, occurred_at=correction.occurred_at, parents=[correction])
    mixed = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((pol_v2,)))
    with SqlStatements(db) as statements:
        emitted = await mixed.append_many([correction, decision])
    assert (emitted, await mixed._is_lineage_head(scope, original.record_id), await mixed.current_decision(scope, decision.lineage)) == ((correction, decision), False, decision)
    assert "pg_advisory_xact_lock" in statements.texts[0] and "unnest" in statements.texts[0]

    first, second = observation(), observation()
    assert first.scope != second.scope and await repository.append_many([first, second]) == (first, second) and await repository.append_many([]) == ()


async def test_AC_audit_trace_record_9_batch_failures_and_head_chunks(db) -> None:
    policy = decision_policy()
    registry = TraceDecisionPolicyRegistry((policy,))
    repository = SqlTraceRecordRepository(db, registry)
    scope = TraceScope.tenant(uuid4())
    parent = observation(scope=scope)
    head = TraceRecord.decision(scope=scope, target=parent.target, policy=policy, execution_id=parent.execution_id, occurred_at=parent.occurred_at, parents=[parent])
    await repository.append_many([parent, head])

    other_parent = observation(scope=scope, execution_id="execution-2")
    fork = TraceRecord.decision(scope=scope, target=parent.target, policy=policy, execution_id=other_parent.execution_id, occurred_at=other_parent.occurred_at, parents=[other_parent])
    unrelated = observation(scope=scope, target_id="unrelated")
    with pytest.raises(TraceRecordPersistenceError, match="must supersede"):
        await repository.append_many([unrelated, other_parent, fork])
    assert await db.scalar(select(func.count()).select_from(TraceRecordRow).where(TraceRecordRow.scope_id == scope.id)) == 2
    assert all((scope, r.record_id) not in repository._cache for r in (unrelated, other_parent, fork))

    fresh = observation(scope=scope, target_id="fresh", execution_id="execution-3")
    d1 = TraceRecord.decision(scope=scope, target=fresh.target, policy=policy, execution_id=fresh.execution_id, occurred_at=fresh.occurred_at, parents=[fresh])
    d2 = TraceRecord.decision(scope=scope, target=fresh.target, policy=policy, execution_id=fresh.execution_id, occurred_at=fresh.occurred_at.replace(microsecond=9), parents=[fresh])
    with pytest.raises(TraceRecordPersistenceError, match="must supersede"):
        await repository.append_many([fresh, d1, d2])
    assert (scope, fresh.record_id) not in repository._cache

    p_unreg = observation(scope=scope, target_id="unreg")
    d_unreg = TraceRecord.decision(scope=scope, target=p_unreg.target, policy=policy, execution_id=p_unreg.execution_id, occurred_at=p_unreg.occurred_at, parents=[p_unreg])
    for repo_case, recs, match in ((repository, [d_unreg, p_unreg], "parent is missing"), (SqlTraceRecordRepository(db), [p_unreg, d_unreg], "no registered")):
        with pytest.raises(TraceRecordPersistenceError, match=match):
            await repo_case.append_many(recs)
    db.info.clear()
    await SqlTraceRecordRepository(db).append(p_unreg)
    await SqlTraceRecordRepository(db).append(observation(scope=scope, target_id="unreg", target_version="v2", assertion_version="v2", supersedes_id=p_unreg.record_id, score="0.5"))
    with pytest.raises(TraceRecordPersistenceError, match="current parent"):
        await SqlTraceRecordRepository(db, registry).append_many([d_unreg])

    db.info.clear()
    corrupt_repo = SqlTraceRecordRepository(db, registry)
    with patch.object(corrupt_repo, "_restore", AsyncMock(side_effect=RuntimeError("row is corrupt"))), pytest.raises(TraceRecordPersistenceError, match="TraceRecord read failed: row is corrupt"):
        await corrupt_repo.append_many([p_unreg])

    db.info.clear()
    flush_scope, flush_repo = TraceScope.tenant(uuid4()), SqlTraceRecordRepository(db, registry)
    flush_fail_records = _causal_set(flush_scope, 2, policy=policy)
    with patch.object(db, "flush", AsyncMock(side_effect=SQLAlchemyError("insert refused"))), pytest.raises(TraceRecordPersistenceError, match="insert refused"):
        await flush_repo.append_many(flush_fail_records)
    assert all((flush_scope, r.record_id) not in flush_repo._cache and (flush_scope, r.record_id) not in flush_repo._ancestry_cache and (flush_scope, r.record_id) not in flush_repo._lineage_head_cache for r in flush_fail_records) and not flush_repo._decision_head_cache

    chunk_scope = TraceScope.tenant(uuid4())
    chunk_records = _causal_set(chunk_scope, 5, policy=policy)
    await repository.append_many(chunk_records)
    decisions, absent = [r for r in chunk_records if r.record_type.value == "decision"], observation(scope=chunk_scope, target_id="absent").lineage
    with patch("src.audit.extension.trace_repository._READ_CHUNK_SIZE", 2), SqlStatements(db) as chunked:
        found = await repository.lineages_with_decision_head(chunk_scope, [*(d.lineage for d in decisions), absent])
    assert (found, len(chunked.texts), await repository.lineages_with_decision_head(chunk_scope, [])) == ({d.lineage for d in decisions}, 3, set())

    ambiguous_db = AsyncMock(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [("financial_fact", "x", "promotion", "y")] * 2)))
    with pytest.raises(TraceRecordPersistenceError, match="ambiguous physical"):
        await SqlTraceRecordRepository(ambiguous_db).lineages_with_decision_head(chunk_scope, [absent])


async def test_AC_audit_trace_record_9_collision_and_emitter_dispatch() -> None:
    record = observation()
    forged = MagicMock(content_digest="0" * 64, record_id=record.record_id)
    with pytest.raises(TraceRecordPersistenceError, match="record id collision"):
        await SqlTraceRecordRepository(AsyncMock())._append_fresh_set((record, forged))
    repo = SqlTraceRecordRepository(AsyncMock())
    repo._cache[record.scope, record.record_id] = forged
    with pytest.raises(TraceRecordPersistenceError, match="record id collision"):
        await repo.append_many([record])

    first, second = observation(), observation()
    sets, appended = [], []
    batch = type("Batch", (), {"append_many": staticmethod(lambda recs: sets.append(tuple(recs)) or _aret(tuple(recs)))})()
    single = SimpleNamespace(append=lambda rec: (appended.append(rec) or _aret(rec)))
    mock_repo = MagicMock(append=AsyncMock(side_effect=lambda r: r))
    assert (await TraceEmitter(batch).emit_many([first, second]), sets, await TraceEmitter(single).emit_many([first, second]), appended, await TraceEmitter(mock_repo).emit_many([first])) == (
        (first, second), [(first, second)], (first, second), [first, second], (first,),
    )


async def _aret(val):
    return val


async def test_AC_audit_trace_record_10_proof_cache_invalidation_and_transactions(db) -> None:
    policy = decision_policy()
    registry = TraceDecisionPolicyRegistry((policy,))
    repository = SqlTraceRecordRepository(db, registry)
    c_scope = TraceScope.tenant(uuid4())
    committed = _causal_set(c_scope, 1, policy=policy)
    await repository.append_many(committed)
    assert repository._cache and repository._decision_head_cache
    await db.commit()
    assert not (repository._cache or repository._ancestry_cache or repository._lineage_head_cache or repository._decision_head_cache)
    assert await repository.get(c_scope, committed[1].record_id) == committed[1]

    sp = await db.begin_nested()
    rb = observation(scope=c_scope, target_id="rolled-back")
    await repository.append_many([rb])
    assert (c_scope, rb.record_id) in repository._cache
    await sp.rollback()
    assert (c_scope, rb.record_id) not in repository._cache and await repository.get(c_scope, rb.record_id) is None and await repository.get(c_scope, committed[1].record_id) == committed[1]

    async with db.begin_nested():
        rel = observation(scope=c_scope, target_id="released")
        await repository.append_many([rel])
    assert (c_scope, rel.record_id) in repository._cache
    with SqlStatements(db) as stmts:
        assert await repository._has_current_ancestry(c_scope, rel.record_id, frozenset())
    assert stmts.texts == []

    scope = TraceScope.tenant(uuid4())
    parent, dec = _causal_set(scope, 1, policy=policy)
    single = observation(scope=scope, target_id="single")
    await repository.append_many([parent, dec, single])
    with SqlStatements(db) as stmts:
        assert (
            await repository.get(scope, dec.record_id),
            await repository._is_lineage_head(scope, dec.record_id),
            await repository._has_current_ancestry(scope, dec.record_id, frozenset()),
            await repository._has_current_ancestry(scope, parent.record_id, frozenset({dec.record_id})),
            await repository.current_decision(scope, dec.lineage),
            await repository._has_current_ancestry(scope, single.record_id, frozenset()),
        ) == (dec, True, True, True, dec, True)
    assert stmts.texts == []

    await repository.append(observation(scope=scope, target_id=parent.target.id, target_version="v2", assertion_version="v2", supersedes_id=parent.record_id, score="0.5"))
    head = await repository.decision_head(scope, dec.lineage)
    assert await repository.current_decision(scope, dec.lineage) is None and head is not None and head.ancestry_current is False
