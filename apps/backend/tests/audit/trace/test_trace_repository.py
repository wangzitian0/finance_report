"""AC-audit.trace-record.4: append-only SQL repository."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
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
)
from src.audit.extension.trace_repository import _row_from_record
from src.audit.orm import TraceRecordParentRow, TraceRecordRow

from .conftest import authority, decision_policy, observation


def _parent_row(record: TraceRecord, parent: TraceRecord) -> TraceRecordParentRow:
    return TraceRecordParentRow(
        scope_kind=record.scope.kind,
        scope_id=record.scope.id,
        record_id=record.record_id,
        parent_id=parent.record_id,
    )


async def _insert_graph_directly(
    db,
    row: TraceRecordRow,
    parent_link: TraceRecordParentRow,
) -> None:
    db.add(row)
    await db.flush()
    db.add(parent_link)
    await db.flush()
    await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


async def test_AC_audit_trace_record_4_repository_is_append_only_and_fail_closed(db):
    record = observation()
    repository = SqlTraceRecordRepository(db)

    first = await repository.append(record)
    duplicate = await repository.append(record)
    assert duplicate.record_id == first.record_id
    assert await repository.get(record.scope, record.record_id) == record
    assert await repository.get(TraceScope.tenant(uuid4()), record.record_id) is None
    assert await TraceEmitter(repository).emit(record) == record

    correction = observation(
        scope=record.scope,
        target_id=record.target.id,
        target_version="v2",
        assertion_version="v2",
        supersedes_id=record.record_id,
        score="0.5",
    )
    await repository.append(correction)
    assert await repository.get(record.scope, correction.record_id) == correction

    # Observations are measurements, not singleton authority heads.
    repeated_measurement = observation(
        scope=record.scope,
        target_id=record.target.id,
        execution_id="execution-2",
        score="0.25",
    )
    await repository.append(repeated_measurement)

    wrong_lineage_correction = observation(
        scope=record.scope,
        target_id=record.target.id,
        assertion_id="different-assertion",
        supersedes_id=correction.record_id,
    )
    with pytest.raises(TraceRecordPersistenceError, match="lineage"):
        await repository.append(wrong_lineage_correction)

    with pytest.raises(DBAPIError, match="append-only"):
        await db.execute(
            update(TraceRecordRow).where(TraceRecordRow.id == record.record_id).values(reason_code="mutated")
        )
    await db.rollback()

    failing_db = AsyncMock()
    failing_db.execute.side_effect = RuntimeError("database unavailable")
    with pytest.raises(TraceRecordPersistenceError, match="database unavailable"):
        await SqlTraceRecordRepository(failing_db).append(observation())


async def test_decision_head_replays_policy_and_can_advance_versions(db):
    policy_v1 = decision_policy(assertion_version="v1")
    policy_v2 = decision_policy(assertion_version="v2")
    repository = SqlTraceRecordRepository(
        db,
        TraceDecisionPolicyRegistry((policy_v1, policy_v2)),
    )
    parent_v1 = observation()
    await repository.append(parent_v1)
    decision_v1 = TraceRecord.decision(
        scope=parent_v1.scope,
        target=parent_v1.target,
        policy=policy_v1,
        execution_id=parent_v1.execution_id,
        occurred_at=parent_v1.occurred_at,
        parents=[parent_v1],
    )
    await repository.append(decision_v1)
    assert await repository.current_decision(parent_v1.scope, decision_v1.lineage) == decision_v1

    parent_v2 = observation(
        scope=parent_v1.scope,
        target_version="v2",
        assertion_id=parent_v1.assertion.id,
        assertion_version="v2",
        execution_id="execution-2",
    )
    await repository.append(parent_v2)
    decision_v2 = TraceRecord.decision(
        scope=parent_v1.scope,
        target=parent_v2.target,
        policy=policy_v2,
        execution_id=parent_v2.execution_id,
        occurred_at=parent_v2.occurred_at.replace(microsecond=1),
        parents=[parent_v2],
        supersedes_id=decision_v1.record_id,
    )
    await repository.append(decision_v2)
    assert decision_v2.lineage == decision_v1.lineage
    assert decision_v2.target.version == "v2"
    assert decision_v2.assertion.version == "v2"
    assert await repository.current_decision(parent_v1.scope, decision_v1.lineage) == decision_v2

    fork = TraceRecord.decision(
        scope=parent_v1.scope,
        target=parent_v2.target,
        policy=policy_v2,
        execution_id=parent_v2.execution_id,
        occurred_at=parent_v2.occurred_at,
        parents=[parent_v2],
    )
    with pytest.raises(TraceRecordPersistenceError, match="must supersede"):
        await repository.append(fork)


async def test_parent_correction_invalidates_authority_without_forking_lineage(db):
    policy = decision_policy()
    repository = SqlTraceRecordRepository(
        db,
        TraceDecisionPolicyRegistry((policy,)),
    )
    parent = observation()
    await repository.append(parent)
    decision = TraceRecord.decision(
        scope=parent.scope,
        target=parent.target,
        policy=policy,
        execution_id=parent.execution_id,
        occurred_at=parent.occurred_at,
        parents=[parent],
    )
    await repository.append(decision)

    correction = observation(
        scope=parent.scope,
        target_version="v2",
        assertion_version="v2",
        execution_id="execution-2",
        supersedes_id=parent.record_id,
    )
    await repository.append(correction)

    assert await repository.current_decision(parent.scope, decision.lineage) is None

    replacement = TraceRecord.decision(
        scope=parent.scope,
        target=correction.target,
        policy=policy,
        execution_id=correction.execution_id,
        occurred_at=correction.occurred_at,
        parents=[correction],
        supersedes_id=decision.record_id,
    )
    await repository.append(replacement)
    assert await repository.current_decision(parent.scope, decision.lineage) == replacement


async def test_repository_replays_policy_instead_of_trusting_decision_fields(db):
    policy = decision_policy()
    repository = SqlTraceRecordRepository(
        db,
        TraceDecisionPolicyRegistry((policy,)),
    )
    parent = observation()
    await repository.append(parent)
    forged = TraceRecord._construct(
        record_type=TraceRecordType.DECISION,
        scope=parent.scope,
        target=parent.target,
        target_class=policy.target_class,
        assertion=policy.assertion,
        authority=policy.authority,
        result=TraceResult.REVIEW,
        execution_id=parent.execution_id,
        causality=policy.causality,
        evidence_manifest_digest="c" * 64,
        occurred_at=parent.occurred_at,
        parent_ids=(parent.record_id,),
        supersedes_id=None,
        score=None,
        reason_code="caller_selected_result",
    )

    with pytest.raises(TraceRecordPersistenceError, match="policy replay"):
        await repository.append(forged)


async def test_repository_rejects_unregistered_missing_and_superseded_parents(db):
    policy = decision_policy()
    parent = observation()
    decision = TraceRecord.decision(
        scope=parent.scope,
        target=parent.target,
        policy=policy,
        execution_id=parent.execution_id,
        occurred_at=parent.occurred_at,
        parents=[parent],
    )

    with pytest.raises(TraceRecordPersistenceError, match="parent is missing"):
        await SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,))).append(decision)

    await SqlTraceRecordRepository(db).append(parent)
    with pytest.raises(TraceRecordPersistenceError, match="no registered"):
        await SqlTraceRecordRepository(db).append(decision)

    correction = observation(
        scope=parent.scope,
        target_version="v2",
        assertion_version="v2",
        supersedes_id=parent.record_id,
        score="0.5",
    )
    await SqlTraceRecordRepository(db).append(correction)
    with pytest.raises(TraceRecordPersistenceError, match="current parent"):
        await SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,))).append(decision)


async def test_database_rejects_cross_scope_supersession_without_repository(db):
    repository = SqlTraceRecordRepository(db)
    parent = observation()
    await repository.append(parent)
    cross_scope = observation(
        target_id=parent.target.id,
        supersedes_id=parent.record_id,
    )

    with pytest.raises(DBAPIError, match="fk_trace_supersedes_scope"):
        async with db.begin_nested():
            db.add(_row_from_record(cross_scope))
            await db.flush()


async def test_database_rejects_stale_or_reclassified_supersession(db):
    original = observation()
    repository = SqlTraceRecordRepository(db)
    await repository.append(original)
    correction = observation(
        scope=original.scope,
        target_version="v2",
        assertion_version="v2",
        supersedes_id=original.record_id,
    )
    await repository.append(correction)

    stale = observation(
        scope=original.scope,
        target_version="v3",
        assertion_version="v3",
        supersedes_id=original.record_id,
    )
    with pytest.raises(DBAPIError, match="current head"):
        async with db.begin_nested():
            db.add(_row_from_record(stale))
            await db.flush()

    reclassified = observation(
        scope=original.scope,
        target_version="v3",
        assertion_version="v3",
        target_class=TraceTargetClass.GENERAL,
        supersedes_id=correction.record_id,
    )
    with pytest.raises(DBAPIError, match="stable lineage"):
        async with db.begin_nested():
            db.add(_row_from_record(reclassified))
            await db.flush()


async def test_database_rejects_authority_fork_without_repository(db):
    policy = decision_policy(assertion_id="database-singleton")
    repository = SqlTraceRecordRepository(
        db,
        TraceDecisionPolicyRegistry((policy,)),
    )
    parent = observation()
    await repository.append(parent)
    decision = TraceRecord.decision(
        scope=parent.scope,
        target=parent.target,
        policy=policy,
        execution_id=parent.execution_id,
        occurred_at=parent.occurred_at,
        parents=[parent],
    )
    await repository.append(decision)
    fork = TraceRecord.decision(
        scope=parent.scope,
        target=parent.target,
        policy=policy,
        execution_id=parent.execution_id,
        occurred_at=parent.occurred_at.replace(microsecond=1),
        parents=[parent],
    )

    with pytest.raises(DBAPIError, match="already has a current head"):
        async with db.begin_nested():
            db.add(_row_from_record(fork))
            await db.flush()


async def test_database_rejects_decision_without_parent_links(db):
    policy = decision_policy(assertion_id="direct-sql")
    parent = observation()
    await SqlTraceRecordRepository(db).append(parent)
    decision = TraceRecord.decision(
        scope=parent.scope,
        target=parent.target,
        policy=policy,
        execution_id=parent.execution_id,
        occurred_at=parent.occurred_at,
        parents=[parent],
    )

    with pytest.raises(DBAPIError, match="requires at least one parent"):
        async with db.begin_nested():
            db.add(_row_from_record(decision))
            await db.flush()
            await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


async def test_database_rejects_late_parent_link_that_rewrites_a_decision(db):
    policy = decision_policy(assertion_id="sealed-parent-set")
    first = observation()
    second = observation(
        scope=first.scope,
        assertion_id="second-parent",
    )
    repository = SqlTraceRecordRepository(
        db,
        TraceDecisionPolicyRegistry((policy,)),
    )
    await repository.append(first)
    await repository.append(second)
    decision = TraceRecord.decision(
        scope=first.scope,
        target=first.target,
        policy=policy,
        execution_id=first.execution_id,
        occurred_at=first.occurred_at,
        parents=[first],
    )
    await repository.append(decision)
    await db.commit()

    with pytest.raises(DBAPIError, match="parent link count"):
        async with db.begin_nested():
            db.add(_parent_row(decision, second))
            await db.flush()
            await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


async def test_database_rejects_cyclic_decision_parents(db):
    parent = observation()
    first = TraceRecord.decision(
        scope=parent.scope,
        target=parent.target,
        policy=decision_policy(assertion_id="cycle-a"),
        execution_id=parent.execution_id,
        occurred_at=parent.occurred_at,
        parents=[parent],
    )
    second = TraceRecord.decision(
        scope=parent.scope,
        target=parent.target,
        policy=decision_policy(assertion_id="cycle-b"),
        execution_id=parent.execution_id,
        occurred_at=parent.occurred_at,
        parents=[parent],
    )

    with pytest.raises(DBAPIError, match="must be acyclic"):
        async with db.begin_nested():
            db.add_all((_row_from_record(first), _row_from_record(second)))
            await db.flush()
            db.add_all((_parent_row(first, second), _parent_row(second, first)))
            await db.flush()
            await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


async def test_database_rejects_direct_decision_with_cross_target_parent(db):
    policy = decision_policy(assertion_id="direct-cross-target")
    parent = observation()
    await SqlTraceRecordRepository(db).append(parent)
    decision = TraceRecord.decision(
        scope=parent.scope,
        target=parent.target,
        policy=policy,
        execution_id=parent.execution_id,
        occurred_at=parent.occurred_at,
        parents=[parent],
    )
    invalid_row = _row_from_record(decision)
    invalid_row.target_id = "different-target"

    with pytest.raises(DBAPIError, match="cross-target or cross-execution"):
        async with db.begin_nested():
            await _insert_graph_directly(
                db,
                invalid_row,
                _parent_row(decision, parent),
            )


async def test_database_rejects_decision_with_superseded_parent(db):
    policy = decision_policy(assertion_id="stale-parent")
    parent = observation()
    repository = SqlTraceRecordRepository(db)
    await repository.append(parent)
    correction = observation(
        scope=parent.scope,
        target_id=parent.target.id,
        target_version="v2",
        assertion_version="v2",
        supersedes_id=parent.record_id,
    )
    await repository.append(correction)
    stale_decision = TraceRecord.decision(
        scope=parent.scope,
        target=parent.target,
        policy=policy,
        execution_id=parent.execution_id,
        occurred_at=parent.occurred_at,
        parents=[parent],
    )

    with pytest.raises(DBAPIError, match="current parent heads"):
        async with db.begin_nested():
            await _insert_graph_directly(
                db,
                _row_from_record(stale_decision),
                _parent_row(stale_decision, parent),
            )


async def test_database_rejects_financial_llm_authority_without_code_guard(db):
    llm_parent = observation(
        profile=authority(
            tier="LLM-LED",
            proof_kind="property",
            provenance="live_llm",
        )
    )
    await SqlTraceRecordRepository(db).append(llm_parent)
    general_policy = decision_policy(
        assertion_id="unguarded-llm",
        target_class=TraceTargetClass.GENERAL,
    )
    decision = TraceRecord.decision(
        scope=llm_parent.scope,
        target=llm_parent.target,
        policy=general_policy,
        execution_id=llm_parent.execution_id,
        occurred_at=llm_parent.occurred_at,
        parents=[llm_parent],
    )
    invalid_row = _row_from_record(decision)
    invalid_row.target_class = TraceTargetClass.FINANCIAL

    with pytest.raises(DBAPIError, match="financial LLM authority"):
        async with db.begin_nested():
            await _insert_graph_directly(
                db,
                invalid_row,
                _parent_row(decision, llm_parent),
            )


async def test_repository_collision_and_read_failures_are_explicit():
    record = observation()
    collision = MagicMock(content_digest="0" * 64)

    first_db = AsyncMock()
    first = SqlTraceRecordRepository(first_db)
    first.get = AsyncMock(return_value=collision)
    with pytest.raises(TraceRecordPersistenceError, match="record id collision"):
        await first.append(record)

    raced_db = AsyncMock()
    raced = SqlTraceRecordRepository(raced_db)
    raced.get = AsyncMock(side_effect=(None, collision))
    with pytest.raises(TraceRecordPersistenceError, match="record id collision"):
        await raced.append(record)

    failing_db = AsyncMock()
    failing_db.execute.side_effect = RuntimeError("read unavailable")
    failing = SqlTraceRecordRepository(failing_db)
    with pytest.raises(TraceRecordPersistenceError, match="read unavailable"):
        await failing.get(record.scope, record.record_id)
    with pytest.raises(TraceRecordPersistenceError, match="current read failed"):
        await failing.current_decision(record.scope, record.lineage)

    with pytest.raises(TraceRecordPersistenceError, match="cycle"):
        await first._get(record.scope, record.record_id, frozenset({record.record_id}))
    with pytest.raises(TraceRecordPersistenceError, match="cycle"):
        await first._has_current_ancestry(record.scope, record.record_id, frozenset({record.record_id}))


async def test_repository_detects_ambiguous_physical_heads():
    record = observation()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [MagicMock(), MagicMock()]
    db = AsyncMock()
    db.execute.return_value = result

    with pytest.raises(TraceRecordPersistenceError, match="ambiguous physical"):
        await SqlTraceRecordRepository(db)._decision_head_row(record.scope, record.lineage)


async def test_repository_rejects_every_invalid_supersession_shape(db):
    repository = SqlTraceRecordRepository(db)
    original = observation()
    await repository.append(original)

    missing = observation(
        scope=original.scope,
        target_version="v2",
        assertion_version="v2",
        supersedes_id=uuid4(),
    )
    with pytest.raises(TraceRecordPersistenceError, match="superseded record is missing"):
        await repository.append(missing)

    type_change = TraceRecord._construct(
        record_type=TraceRecordType.DECISION,
        scope=original.scope,
        target=original.target,
        target_class=original.target_class,
        assertion=original.assertion,
        authority=original.authority,
        result=TraceResult.AUTHORITATIVE,
        execution_id=original.execution_id,
        causality=decision_policy().causality,
        evidence_manifest_digest="c" * 64,
        occurred_at=original.occurred_at,
        parent_ids=(original.record_id,),
        supersedes_id=original.record_id,
        score=None,
        reason_code="invalid_type_change",
    )
    with pytest.raises(TraceRecordPersistenceError, match="cannot change TraceRecord type"):
        await repository.append(type_change)

    class_change = observation(
        scope=original.scope,
        target_version="v2",
        assertion_version="v2",
        target_class=TraceTargetClass.GENERAL,
        supersedes_id=original.record_id,
    )
    with pytest.raises(TraceRecordPersistenceError, match="target class"):
        await repository.append(class_change)

    correction = observation(
        scope=original.scope,
        target_version="v2",
        assertion_version="v2",
        supersedes_id=original.record_id,
    )
    await repository.append(correction)
    stale = observation(
        scope=original.scope,
        target_version="v3",
        assertion_version="v3",
        supersedes_id=original.record_id,
    )
    with pytest.raises(TraceRecordPersistenceError, match="not a current lineage head"):
        await repository.append(stale)

    tampered = observation(scope=original.scope, target_id="tampered-parent-set")
    object.__setattr__(tampered, "parent_ids", (correction.record_id,))
    object.__setattr__(tampered, "record_id", uuid4())
    with pytest.raises(TraceRecordPersistenceError, match="observation cannot persist parent"):
        await repository.append(tampered)


async def test_repository_rejects_corrupt_persisted_rows_and_policy_replay(db):
    repository = SqlTraceRecordRepository(db)
    record = observation()

    wrong_schema = _row_from_record(record)
    wrong_schema.schema_version = "2"
    with pytest.raises(TraceRecordPersistenceError, match="unsupported persisted"):
        await repository._restore(wrong_schema, frozenset())

    wrong_count = _row_from_record(record)
    wrong_count.parent_count = 1
    with pytest.raises(TraceRecordPersistenceError, match="parent count mismatch"):
        await repository._restore(wrong_count, frozenset())

    wrong_digest = _row_from_record(record)
    wrong_digest.content_digest = "0" * 64
    with pytest.raises(TraceRecordPersistenceError, match="digest mismatch"):
        await repository._restore(wrong_digest, frozenset())

    policy = decision_policy(assertion_id="restore-parent")
    decision = TraceRecord.decision(
        scope=record.scope,
        target=record.target,
        policy=policy,
        execution_id=record.execution_id,
        occurred_at=record.occurred_at,
        parents=[record],
    )
    parent_result = MagicMock()
    parent_result.scalars.return_value = (record.record_id,)
    fake_db = AsyncMock()
    fake_db.execute.return_value = parent_result
    missing_parent_repository = SqlTraceRecordRepository(
        fake_db,
        TraceDecisionPolicyRegistry((policy,)),
    )
    missing_parent_repository._get = AsyncMock(return_value=None)
    with pytest.raises(TraceRecordPersistenceError, match="persisted decision parent is missing"):
        await missing_parent_repository._restore(_row_from_record(decision), frozenset())

    live_repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,)))
    await live_repository.append(record)
    await live_repository.append(decision)
    replaying = SqlTraceRecordRepository(
        db,
        TraceDecisionPolicyRegistry(
            (
                decision_policy(
                    assertion_id="restore-parent",
                    result=TraceResult.REVIEW,
                ),
            )
        ),
    )
    with pytest.raises(TraceRecordPersistenceError, match="persisted decision policy replay"):
        await replaying.get(record.scope, decision.record_id)


async def test_repository_current_ancestry_handles_missing_and_parentless_records(db):
    repository = SqlTraceRecordRepository(db)
    assert not await repository._has_current_ancestry(
        TraceScope.tenant(uuid4()),
        uuid4(),
        frozenset(),
    )

    no_superseder = MagicMock()
    no_superseder.scalar_one_or_none.return_value = None
    decision_type = MagicMock()
    decision_type.scalar_one_or_none.return_value = TraceRecordType.DECISION
    no_parents = MagicMock()
    no_parents.scalars.return_value = ()
    fake_db = AsyncMock()
    fake_db.execute.side_effect = (no_superseder, decision_type, no_parents)
    assert not await SqlTraceRecordRepository(fake_db)._has_current_ancestry(
        TraceScope.tenant(uuid4()),
        uuid4(),
        frozenset(),
    )


async def test_orm_listener_rejects_in_memory_mutation(db):
    row = _row_from_record(observation())
    db.add(row)
    await db.flush()
    loaded = (await db.execute(select(TraceRecordRow).where(TraceRecordRow.id == row.id))).scalar_one()
    loaded.reason_code = "mutated"
    with pytest.raises(ValueError, match="append-only"):
        await db.flush()
