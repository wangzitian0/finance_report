from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from src.audit import (
    SqlTraceRecordRepository,
    TraceDecisionPolicyRegistry,
    TraceEmitter,
    TraceRecord,
    TraceRecordPersistenceError,
    TraceRecordType,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
    current_authoritative_trace_decision_projection,
)
from src.audit.base.trace import TraceCausality
from src.audit.extension.trace_repository import _row_from_record
from src.audit.orm import TraceRecordParentRow, TraceRecordRow
from tests.audit.trace.conftest import FixtureDecisionPolicy, authority, decision as _dec, decision_policy, observation

_parent_row = lambda record, parent: TraceRecordParentRow(scope_kind=record.scope.kind, scope_id=record.scope.id, record_id=record.record_id, parent_id=parent.record_id)
_decision = lambda parent, **kw: _dec(kw.pop("parents", [parent]), **kw)


async def _insert_graph_directly(db, row: TraceRecordRow, parent_link: TraceRecordParentRow) -> None:
    db.add(row)
    await db.flush()
    db.add(parent_link)
    await db.flush()


async def test_AC_audit_trace_record_4_repository_is_append_only_and_fail_closed(db) -> None:
    record = observation()
    repository = SqlTraceRecordRepository(db)
    first, duplicate = await repository.append(record), await repository.append(record)
    correction = observation(scope=record.scope, target_id=record.target.id, target_version="v2", assertion_version="v2", supersedes_id=record.record_id, score="0.5")
    await repository.append(correction)
    await repository.append(observation(scope=record.scope, target_id=record.target.id, execution_id="execution-2", score="0.25"))
    assert (duplicate.record_id, await repository.get(record.scope, record.record_id), await repository.get(TraceScope.tenant(uuid4()), record.record_id), await TraceEmitter(repository).emit(record), await repository.get(record.scope, correction.record_id)) == (
        first.record_id, record, None, record, correction,
    )
    with pytest.raises(TraceRecordPersistenceError, match="lineage"):
        await repository.append(observation(scope=record.scope, target_id=record.target.id, assertion_id="different-assertion", supersedes_id=correction.record_id))
    with pytest.raises(DBAPIError, match="append-only"):
        await db.execute(update(TraceRecordRow).where(TraceRecordRow.id == record.record_id).values(reason_code="mutated"))
    await db.rollback()
    failing_db = AsyncMock(execute=AsyncMock(side_effect=RuntimeError("database unavailable")))
    with pytest.raises(TraceRecordPersistenceError, match="database unavailable"):
        await SqlTraceRecordRepository(failing_db).append(observation())


async def test_decision_head_advances_invalidates_and_tracks_ancestry(db) -> None:
    pv1, pv2, p_head_pol = decision_policy(assertion_version="v1"), decision_policy(assertion_version="v2"), decision_policy(assertion_id="typed-decision-head")
    repo = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((pv1, pv2, p_head_pol)))
    p1 = observation()
    await repo.append(p1)
    d1 = _decision(p1, policy=pv1)
    await repo.append(d1)
    assert await repo.current_decision(p1.scope, d1.lineage) == d1

    p2 = observation(scope=p1.scope, target_version="v2", assertion_id=p1.assertion.id, assertion_version="v2", execution_id="execution-2")
    await repo.append(p2)
    d2 = _decision(p2, policy=pv2, occurred_at=p2.occurred_at.replace(microsecond=1), supersedes_id=d1.record_id)
    await repo.append(d2)
    assert (d2.lineage, d2.target.version, d2.assertion.version, await repo.current_decision(p1.scope, d1.lineage)) == (d1.lineage, "v2", "v2", d2)
    with pytest.raises(TraceRecordPersistenceError, match="must supersede"):
        await repo.append(_decision(p2, policy=pv2))

    proj = current_authoritative_trace_decision_projection(p1.scope).subquery()
    assert d2.record_id in set((await db.execute(select(proj.c.decision_id))).scalars())
    await repo.append(observation(scope=p1.scope, target_version="v3", assertion_version="v3", execution_id="execution-3", supersedes_id=p2.record_id))
    assert d2.record_id not in set((await db.execute(select(proj.c.decision_id))).scalars())

    p_head = observation(assertion_id="typed-decision-head-input")
    d_head = _decision(p_head, policy=p_head_pol)
    assert await repo.decision_head(p_head.scope, d_head.lineage) is None
    await repo.append(p_head)
    await repo.append(d_head)
    current = await repo.decision_head(p_head.scope, d_head.lineage)
    assert (current.record, current.ancestry_current, await repo.current_decision(p_head.scope, d_head.lineage)) == (d_head, True, d_head)

    p_corr = observation(scope=p_head.scope, target_version="v2", assertion_id=p_head.assertion.id, assertion_version="v2", execution_id="execution-2", supersedes_id=p_head.record_id)
    await repo.append(p_corr)
    stale = await repo.decision_head(p_head.scope, d_head.lineage)
    repo._restore = AsyncMock(wraps=repo._restore)
    assert (stale.record, stale.ancestry_current, await repo.current_decision(p_head.scope, d_head.lineage)) == (d_head, False, None)
    repo._restore.assert_not_awaited()
    replacement = _decision(p_corr, policy=p_head_pol, supersedes_id=d_head.record_id)
    await repo.append(replacement)
    assert await repo.current_decision(p_head.scope, d_head.lineage) == replacement


async def test_repository_rejects_forged_unregistered_missing_and_superseded_parents(db) -> None:
    policy, parent = decision_policy(), observation()
    decision = _decision(parent, policy=policy)
    forged = TraceRecord._construct(
        record_type=TraceRecordType.DECISION, scope=parent.scope, target=parent.target, target_class=policy.target_class,
        assertion=policy.assertion, authority=policy.authority, result=TraceResult.REVIEW, execution_id=parent.execution_id,
        causality=policy.causality, evidence_manifest_digest="c" * 64, occurred_at=parent.occurred_at,
        parent_ids=(parent.record_id,), supersedes_id=None, score=None, reason_code="caller_selected_result",
    )
    with pytest.raises(TraceRecordPersistenceError, match="parent is missing"):
        await SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,))).append(decision)
    await SqlTraceRecordRepository(db).append(parent)
    for repo, rec, match in (
        (SqlTraceRecordRepository(db), decision, "no registered"),
        (SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,))), forged, "policy replay"),
    ):
        with pytest.raises(TraceRecordPersistenceError, match=match):
            await repo.append(rec)
    await SqlTraceRecordRepository(db).append(observation(scope=parent.scope, target_version="v2", assertion_version="v2", supersedes_id=parent.record_id, score="0.5"))
    with pytest.raises(TraceRecordPersistenceError, match="current parent"):
        await SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,))).append(decision)


async def test_database_constraints_reject_invalid_graphs_without_repository(db) -> None:
    async def _check(match: str, fn) -> None:
        with pytest.raises(DBAPIError, match=match):
            async with db.begin_nested():
                await fn()
                await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    async def _add_flush(*objs) -> None:
        db.add_all(objs)
        await db.flush()

    policy, parent = decision_policy(assertion_id="db-guard"), observation()
    repo = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,)))
    await repo.append(parent)
    await _check("fk_trace_supersedes_scope", lambda: _add_flush(_row_from_record(observation(target_id=parent.target.id, supersedes_id=parent.record_id))))
    await _check("requires at least one parent", lambda: _add_flush(_row_from_record(_decision(parent, policy=policy))))

    d = _decision(parent, policy=policy)
    bad_row = _row_from_record(d)
    bad_row.target_id = "different-target"
    await _check("cross-target or cross-execution", lambda: _insert_graph_directly(db, bad_row, _parent_row(d, parent)))
    a, b = _decision(parent, policy=decision_policy(assertion_id="cycle-a")), _decision(parent, policy=decision_policy(assertion_id="cycle-b"))

    async def _cycle() -> None:
        await _add_flush(_row_from_record(a), _row_from_record(b))
        await _add_flush(_parent_row(a, b), _parent_row(b, a))

    await _check("must be acyclic", _cycle)

    second_obs = observation(scope=parent.scope, assertion_id="obs-parent")
    await repo.append(second_obs)
    await _check("OBSERVATION cannot have parent links", lambda: _add_flush(_parent_row(parent, second_obs)))

    llm_parent = observation(profile=authority(tier="LLM-LED", proof_kind="property", provenance="live_llm"))
    await repo.append(llm_parent)
    llm_dec = _decision(llm_parent, policy=decision_policy(assertion_id="unguarded-llm", target_class=TraceTargetClass.GENERAL))
    llm_row = _row_from_record(llm_dec)
    llm_row.target_class = TraceTargetClass.FINANCIAL
    await _check("financial LLM authority", lambda: _insert_graph_directly(db, llm_row, _parent_row(llm_dec, llm_parent)))

    corr = observation(scope=parent.scope, target_version="v2", assertion_version="v2", supersedes_id=parent.record_id)
    await repo.append(corr)
    await _check("current head", lambda: _add_flush(_row_from_record(observation(scope=parent.scope, target_version="v3", assertion_version="v3", supersedes_id=parent.record_id))))
    await _check("stable lineage", lambda: _add_flush(_row_from_record(observation(scope=parent.scope, target_version="v3", assertion_version="v3", target_class=TraceTargetClass.GENERAL, supersedes_id=corr.record_id))))
    await _check("current parent heads", lambda: _insert_graph_directly(db, _row_from_record(d), _parent_row(d, parent)))

    head_parent = observation(scope=parent.scope, target_id="subject-head")
    await repo.append(head_parent)
    head_dec = _decision(head_parent, policy=policy)
    await repo.append(head_dec)
    await _check("already has a current head", lambda: _add_flush(_row_from_record(_decision(head_parent, policy=policy, occurred_at=head_parent.occurred_at.replace(microsecond=1)))))
    await db.commit()
    await _check("parent link count", lambda: _add_flush(_parent_row(head_dec, second_obs)))


async def test_repository_collision_read_failures_and_ordered_restore() -> None:
    record = observation()
    collision = MagicMock(content_digest="0" * 64)
    first = SqlTraceRecordRepository(AsyncMock())
    first.get = AsyncMock(return_value=collision)
    raced = SqlTraceRecordRepository(AsyncMock())
    raced.get = AsyncMock(side_effect=(None, collision))
    failing = SqlTraceRecordRepository(AsyncMock(execute=AsyncMock(side_effect=RuntimeError("read unavailable"))))
    for coro, match in (
        (first.append(record), "record id collision"),
        (raced.append(record), "record id collision"),
        (failing.get(record.scope, record.record_id), "read unavailable"),
        (failing.current_decision(record.scope, record.lineage), "current read failed"),
        (first._get(record.scope, record.record_id, frozenset({record.record_id})), "cycle"),
        (first._has_current_ancestry(record.scope, record.record_id, frozenset({record.record_id})), "cycle"),
    ):
        with pytest.raises(TraceRecordPersistenceError, match=match):
            await coro

    amb_db = AsyncMock(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [MagicMock(), MagicMock()]))))
    with pytest.raises(TraceRecordPersistenceError, match="ambiguous physical"):
        await SqlTraceRecordRepository(amb_db)._decision_head_row(record.scope, record.lineage)

    p2 = observation(scope=record.scope, assertion_id="second-parent")
    p1 = observation(scope=p2.scope, assertion_id="first-parent")
    pol = decision_policy(assertion_id="ordered-restore")
    dec = _decision(p1, policy=pol, parents=[p1, p2])
    repo = SqlTraceRecordRepository(AsyncMock(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: tuple(reversed(dec.parent_ids))))), TraceDecisionPolicyRegistry((pol,)))
    parents_map = {p.record_id: p for p in (p1, p2)}
    repo._get = AsyncMock(side_effect=lambda _s, rid, _v: parents_map[rid])
    assert await repo._restore(_row_from_record(dec), frozenset()) == dec


async def test_repository_rejects_invalid_supersessions_and_corrupt_rows(db) -> None:
    repository, original = SqlTraceRecordRepository(db), observation()
    await repository.append(original)
    correction = observation(scope=original.scope, target_version="v2", assertion_version="v2", supersedes_id=original.record_id)
    await repository.append(correction)
    tampered = observation(scope=original.scope, target_id="tampered-parent-set")
    object.__setattr__(tampered, "parent_ids", (correction.record_id,))
    object.__setattr__(tampered, "record_id", uuid4())
    type_change = TraceRecord._construct(
        record_type=TraceRecordType.DECISION, scope=original.scope, target=original.target, target_class=original.target_class,
        assertion=original.assertion, authority=original.authority, result=TraceResult.AUTHORITATIVE, execution_id=original.execution_id,
        causality=decision_policy().causality, evidence_manifest_digest="c" * 64, occurred_at=original.occurred_at,
        parent_ids=(original.record_id,), supersedes_id=original.record_id, score=None, reason_code="invalid_type_change",
    )
    for bad, match in (
        (observation(scope=original.scope, target_version="v2", assertion_version="v2", supersedes_id=uuid4()), "superseded record is missing"),
        (type_change, "cannot change TraceRecord type"),
        (observation(scope=original.scope, target_version="v2", assertion_version="v2", target_class=TraceTargetClass.GENERAL, supersedes_id=original.record_id), "target class"),
        (observation(scope=original.scope, target_version="v3", assertion_version="v3", supersedes_id=original.record_id), "not a current lineage head"),
        (tampered, "observation cannot persist parent"),
    ):
        with pytest.raises(TraceRecordPersistenceError, match=match):
            await repository.append(bad)

    for field, val, match in (("schema_version", "2", "unsupported persisted"), ("parent_count", 1, "parent count mismatch"), ("content_digest", "0" * 64, "digest mismatch")):
        row = _row_from_record(original)
        setattr(row, field, val)
        with pytest.raises(TraceRecordPersistenceError, match=match):
            await repository._restore(row, frozenset())

    policy = decision_policy(assertion_id="restore-parent")
    decision = _decision(original, policy=policy)
    missing_parent_repo = SqlTraceRecordRepository(
        AsyncMock(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: (original.record_id,)))),
        TraceDecisionPolicyRegistry((policy,)),
    )
    missing_parent_repo._get = AsyncMock(return_value=None)
    with pytest.raises(TraceRecordPersistenceError, match="persisted decision parent is missing"):
        await missing_parent_repo._restore(_row_from_record(decision), frozenset())

    live_dec = _decision(correction, policy=policy)
    await SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,))).append(live_dec)
    replaying = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((decision_policy(assertion_id="restore-parent", result=TraceResult.REVIEW),)))
    with pytest.raises(TraceRecordPersistenceError, match="persisted decision policy replay"):
        await replaying.get(original.scope, live_dec.record_id)


async def test_repository_ancestry_orm_listener_caches_and_isolation(db) -> None:
    assert not await SqlTraceRecordRepository(db)._has_current_ancestry(TraceScope.tenant(uuid4()), uuid4(), frozenset())
    fake_db = AsyncMock(execute=AsyncMock(side_effect=(SimpleNamespace(scalar_one_or_none=lambda: None), SimpleNamespace(scalar_one_or_none=lambda: TraceRecordType.DECISION), SimpleNamespace(scalars=lambda: ()))))
    assert not await SqlTraceRecordRepository(fake_db)._has_current_ancestry(TraceScope.tenant(uuid4()), uuid4(), frozenset())

    row = _row_from_record(observation())
    db.add(row)
    await db.flush()
    (await db.execute(select(TraceRecordRow).where(TraceRecordRow.id == row.id))).scalar_one().reason_code = "mutated"
    with pytest.raises(ValueError, match="append-only"):
        await db.flush()
    await db.rollback()

    repo, record = SqlTraceRecordRepository(db), observation()
    await repo.append(record)
    assert await repo._has_current_ancestry(record.scope, record.record_id, frozenset()) and repo._lineage_head_cache[record.scope, record.record_id] is True and repo._ancestry_cache[record.scope, record.record_id] is True
    with patch.object(repo._db, "execute", side_effect=RuntimeError("database query attempted")):
        repo2 = SqlTraceRecordRepository(db)
        assert (await repo._has_current_ancestry(record.scope, record.record_id, frozenset()), await repo._is_lineage_head(record.scope, record.record_id), repo2._cache is repo._cache, repo2._lineage_head_cache is repo._lineage_head_cache, repo2._ancestry_cache is repo._ancestry_cache, await repo2.get(record.scope, record.record_id)) == (
            True, True, True, True, True, record,
        )

    await repo.append(observation(scope=record.scope, target_id=record.target.id, target_version="v2", assertion_version="v2", supersedes_id=record.record_id, score="0.5"))
    assert (record.scope, record.record_id) not in repo._lineage_head_cache and (record.scope, record.record_id) not in repo._ancestry_cache and not await repo._is_lineage_head(record.scope, record.record_id) and not await repo._has_current_ancestry(record.scope, record.record_id, frozenset())

    class _UnhashablePolicy(FixtureDecisionPolicy):
        __hash__ = None

    reg = TraceDecisionPolicyRegistry((_UnhashablePolicy(assertion=VersionedTraceRef(kind="promotion", id="unhashable", version="v1"), authority=authority()),))
    assert SqlTraceRecordRepository(db, reg)._cache is SqlTraceRecordRepository(db, reg)._cache

    r2, policy = observation(), decision_policy(assertion_id="cache-isolated-parent")
    d2 = _decision(r2, policy=policy)
    repo_with_policy = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,)))
    await repo_with_policy.append(r2)
    await repo_with_policy.append(d2)
    repo_empty = SqlTraceRecordRepository(db)
    assert repo_empty._cache is not repo_with_policy._cache
    with pytest.raises(TraceRecordPersistenceError, match="no registered decision policy"):
        await repo_empty.get(d2.scope, d2.record_id)


async def test_80_row_trace_creation_and_deferred_trigger_commit_budget(db) -> None:
    index_names = set((await db.scalars(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexname IN ('ix_trace_records_supersedes_lookup', 'ix_trace_record_parents_parent_lookup')"))).all())
    assert index_names == {"ix_trace_records_supersedes_lookup", "ix_trace_record_parents_parent_lookup"}
    scope_kind, scope_id, now = TraceScope.tenant(uuid4()).kind, str(uuid4()), datetime.now(UTC)
    common = {
        "scope_kind": scope_kind, "scope_id": scope_id, "schema_version": "1", "target_kind": "journal_entry",
        "target_version": "1", "target_class": TraceTargetClass.FINANCIAL, "assertion_version": "v1", "authority_package": "ledger",
        "authority_tier": "CODE-ONLY", "proof_kind": "invariant", "provenance": "deterministic_code", "execution_stage": "runtime",
        "assertion_owner_digest": "a" * 64, "producer_version": "1", "evidence_manifest_digest": "b" * 64, "occurred_at": now,
        "supersedes_id": None, "reason_code": "ok",
    }
    records, links = [], []
    for i in range(80):
        tid, eid, inv_id, promo_id = f"entry-{i}", f"exec-{i}", uuid4(), uuid4()
        obs_ids = [uuid4() for _ in range(5)]
        records.extend(
            TraceRecordRow(**common, id=oid, record_type=TraceRecordType.OBSERVATION, target_id=tid, assertion_kind="check", assertion_id=f"ledger.1.{j}", result=TraceResult.PASS, execution_id=eid, causality=None, parent_count=0, score=Decimal("1"), content_digest=f"{scope_id[:8]}-{i:04d}-obs-{j}".ljust(64, "0"))
            for j, oid in enumerate(obs_ids)
        )
        records.extend((
            TraceRecordRow(**common, id=inv_id, record_type=TraceRecordType.DECISION, target_id=tid, assertion_kind="invariant", assertion_id="ledger.1.inv", result=TraceResult.AUTHORITATIVE, execution_id=eid, causality=TraceCausality.DIRECT, parent_count=5, score=None, content_digest=f"{scope_id[:8]}-{i:04d}-inv".ljust(64, "0")),
            TraceRecordRow(**common, id=promo_id, record_type=TraceRecordType.DECISION, target_id=tid, assertion_kind="promotion", assertion_id="ledger.1.promo", result=TraceResult.AUTHORITATIVE, execution_id=eid, causality=TraceCausality.DIRECT, parent_count=1, score=None, content_digest=f"{scope_id[:8]}-{i:04d}-promo".ljust(64, "0")),
        ))
        links.extend([*(TraceRecordParentRow(scope_kind=scope_kind, scope_id=scope_id, record_id=inv_id, parent_id=oid) for oid in obs_ids), TraceRecordParentRow(scope_kind=scope_kind, scope_id=scope_id, record_id=promo_id, parent_id=inv_id)])

    db.add_all(records)
    await db.flush()
    db.add_all(links)
    await db.flush()
    t0 = time.perf_counter()
    await db.execute(text("SET CONSTRAINTS trace_records_validate_links, trace_record_parents_validate_links IMMEDIATE"))
    assert (time.perf_counter() - t0) * 1000.0 < 300.0
