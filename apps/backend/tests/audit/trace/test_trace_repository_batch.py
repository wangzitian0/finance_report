"""AC-audit.trace-record.9 and .10: batch append and the session memo of the SQL repository (#2612).

``append_many`` must write the same rows as one ``append`` per record, with a number of SQL
statements that does not grow with the set. What an append proves must serve later reads of the same
unit of work, and a commit or a rollback must end that proof.
"""

from __future__ import annotations

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

from .conftest import decision_policy, observation

pytestmark = pytest.mark.asyncio


def _causal_set(scope: TraceScope, count: int, *, policy) -> list[TraceRecord]:
    """For each of ``count`` targets: one observation and one decision on it, in causal order."""
    records: list[TraceRecord] = []
    for index in range(count):
        parent = observation(scope=scope, target_id=f"subject-{index}")
        records.append(parent)
        records.append(
            TraceRecord.decision(
                scope=scope,
                target=parent.target,
                policy=policy,
                execution_id=parent.execution_id,
                occurred_at=parent.occurred_at,
                parents=[parent],
            )
        )
    return records


class _Statements:
    """Count the SQL statements that one block sends."""

    def __init__(self, db) -> None:
        self._engine = db.bind.sync_engine
        self.texts: list[str] = []

    def _capture(self, _conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        self.texts.append(statement)

    def __enter__(self) -> _Statements:
        event.listen(self._engine, "before_cursor_execute", self._capture)
        return self

    def __exit__(self, *_exc) -> None:
        event.remove(self._engine, "before_cursor_execute", self._capture)


async def _persisted(db, scope: TraceScope) -> tuple[list[dict], list[tuple]]:
    rows = (await db.execute(select(TraceRecordRow).where(TraceRecordRow.scope_id == scope.id))).scalars().all()
    parents = (
        await db.execute(select(TraceRecordParentRow).where(TraceRecordParentRow.scope_id == scope.id))
    ).scalars()
    return (
        sorted(
            ({column.name: getattr(row, column.name) for column in TraceRecordRow.__table__.columns} for row in rows),
            key=lambda item: str(item["id"]),
        ),
        sorted((link.record_id, link.parent_id) for link in parents),
    )


async def test_AC_audit_trace_record_9_batch_rows_equal_the_rows_of_one_append_per_record(db):
    """AC-audit.trace-record.9: Batch rows equal the rows of one append per record."""
    policy = decision_policy()
    registry = TraceDecisionPolicyRegistry((policy,))
    scope = TraceScope.tenant(uuid4())
    records = _causal_set(scope, 6, policy=policy)

    nested = await db.begin_nested()
    for record in records:
        await SqlTraceRecordRepository(db, registry).append(record)
    sequential = await _persisted(db, scope)
    await nested.rollback()
    assert (await _persisted(db, scope)) == ([], []), "the savepoint removed the rows of the first run"

    emitted = await SqlTraceRecordRepository(db, registry).append_many(records)
    batch = await _persisted(db, scope)

    assert emitted == tuple(records)
    assert len(batch[0]) == 12 and len(batch[1]) == 6
    assert batch == sequential


async def test_AC_audit_trace_record_9_batch_statement_count_does_not_grow_with_the_set(db):
    """AC-audit.trace-record.9: Batch statement count does not grow with the set."""
    policy = decision_policy()
    registry = TraceDecisionPolicyRegistry((policy,))
    small_scope, large_scope, sequential_scope = (TraceScope.tenant(uuid4()) for _ in range(3))

    with _Statements(db) as small:
        await SqlTraceRecordRepository(db, registry).append_many(_causal_set(small_scope, 2, policy=policy))
    with _Statements(db) as large:
        await SqlTraceRecordRepository(db, registry).append_many(_causal_set(large_scope, 30, policy=policy))
    with _Statements(db) as sequential:
        repository = SqlTraceRecordRepository(db, registry)
        for record in _causal_set(sequential_scope, 30, policy=policy):
            await repository.append(record)

    assert len(large.texts) == len(small.texts) <= 6, (len(small.texts), len(large.texts))
    assert len(sequential.texts) >= 10 * len(large.texts), (len(sequential.texts), len(large.texts))


async def test_AC_audit_trace_record_9_batch_takes_the_lineage_locks_in_key_order_before_it_reads(db):
    """AC-audit.trace-record.9: Batch takes the lineage locks in key order before it reads."""
    policy = decision_policy()
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,)))
    records = _causal_set(TraceScope.tenant(uuid4()), 6, policy=policy)
    captured: list[tuple[str, tuple]] = []

    def capture(_conn, _cursor, statement, parameters, _context, _executemany) -> None:
        captured.append((statement, parameters))

    engine = db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        await repository.append_many(records)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    locks = [index for index, (text_, _) in enumerate(captured) if "pg_advisory_xact_lock" in text_]
    reads = [index for index, (text_, _) in enumerate(captured) if text_.startswith("SELECT trace_records")]
    assert len(locks) == 1, "one statement takes every lock"
    assert reads and locks[0] < min(reads), "the checks run under the locks"
    # Six targets, each with an observation lineage and a decision lineage.
    keys = captured[locks[0]][1][0]
    assert len(keys) == len({record.lineage for record in records}) == 12
    assert list(keys) == sorted(keys)


async def test_AC_audit_trace_record_9_batch_append_is_idempotent(db):
    """AC-audit.trace-record.9: Batch append is idempotent."""
    policy = decision_policy()
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,)))
    scope = TraceScope.tenant(uuid4())
    records = _causal_set(scope, 3, policy=policy)
    await repository.append_many(records)
    before = await _persisted(db, scope)

    # A second repository has no memo of the first. It must read the rows and add none.
    db.info.clear()
    again = await SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,))).append_many(
        [*records, records[0]]
    )

    assert again == (*records, records[0])
    assert await _persisted(db, scope) == before


async def test_AC_audit_trace_record_9_batch_refuses_a_second_head_and_leaves_no_trace(db):
    """AC-audit.trace-record.9: Batch refuses a second head and leaves no trace."""
    policy = decision_policy()
    registry = TraceDecisionPolicyRegistry((policy,))
    repository = SqlTraceRecordRepository(db, registry)
    scope = TraceScope.tenant(uuid4())
    parent = observation(scope=scope)
    head = TraceRecord.decision(
        scope=scope,
        target=parent.target,
        policy=policy,
        execution_id=parent.execution_id,
        occurred_at=parent.occurred_at,
        parents=[parent],
    )
    await repository.append_many([parent, head])

    other_parent = observation(scope=scope, execution_id="execution-2")
    fork = TraceRecord.decision(
        scope=scope,
        target=parent.target,
        policy=policy,
        execution_id=other_parent.execution_id,
        occurred_at=other_parent.occurred_at,
        parents=[other_parent],
    )
    unrelated = observation(scope=scope, target_id="unrelated")
    with pytest.raises(TraceRecordPersistenceError, match="must supersede"):
        await repository.append_many([unrelated, other_parent, fork])
    # Nothing of the refused set is persisted or remembered.
    assert (
        await db.scalar(select(func.count()).select_from(TraceRecordRow).where(TraceRecordRow.scope_id == scope.id))
    ) == 2
    for refused in (unrelated, other_parent, fork):
        assert (scope, refused.record_id) not in repository._cache

    # Two decisions of one lineage in one set are a fork too.
    fresh_parent = observation(scope=scope, target_id="fresh", execution_id="execution-3")
    first = TraceRecord.decision(
        scope=scope,
        target=fresh_parent.target,
        policy=policy,
        execution_id=fresh_parent.execution_id,
        occurred_at=fresh_parent.occurred_at,
        parents=[fresh_parent],
    )
    second = TraceRecord.decision(
        scope=scope,
        target=fresh_parent.target,
        policy=policy,
        execution_id=fresh_parent.execution_id,
        occurred_at=fresh_parent.occurred_at.replace(microsecond=9),
        parents=[fresh_parent],
    )
    assert first.record_id != second.record_id and first.lineage == second.lineage
    with pytest.raises(TraceRecordPersistenceError, match="must supersede"):
        await repository.append_many([fresh_parent, first, second])
    assert (scope, fresh_parent.record_id) not in repository._cache


async def test_AC_audit_trace_record_9_batch_refuses_missing_stale_and_unregistered_parents(db):
    """AC-audit.trace-record.9: Batch refuses missing stale and unregistered parents."""
    policy = decision_policy()
    scope = TraceScope.tenant(uuid4())
    parent = observation(scope=scope)
    decision = TraceRecord.decision(
        scope=scope,
        target=parent.target,
        policy=policy,
        execution_id=parent.execution_id,
        occurred_at=parent.occurred_at,
        parents=[parent],
    )
    registry = TraceDecisionPolicyRegistry((policy,))

    # The decision comes before its parent: the parent does not exist yet.
    repository = SqlTraceRecordRepository(db, registry)
    with pytest.raises(TraceRecordPersistenceError, match="parent is missing"):
        await repository.append_many([decision, parent])

    # A decision policy that the repository does not know cannot be replayed.
    with pytest.raises(TraceRecordPersistenceError, match="no registered"):
        await SqlTraceRecordRepository(db).append_many([parent, decision])
    db.info.clear()

    # A parent that a correction superseded is no longer a current head.
    await SqlTraceRecordRepository(db).append(parent)
    correction = observation(
        scope=scope,
        target_version="v2",
        assertion_version="v2",
        supersedes_id=parent.record_id,
        score="0.5",
    )
    await SqlTraceRecordRepository(db).append(correction)
    with pytest.raises(TraceRecordPersistenceError, match="current parent"):
        await SqlTraceRecordRepository(db, registry).append_many([decision])


async def test_AC_audit_trace_record_9_batch_with_a_supersession_keeps_the_per_record_path(db):
    """AC-audit.trace-record.9: Batch with a supersession keeps the per record path."""
    policy = decision_policy()
    registry = TraceDecisionPolicyRegistry((policy,))
    repository = SqlTraceRecordRepository(db, registry)
    scope = TraceScope.tenant(uuid4())
    original = observation(scope=scope)
    await repository.append_many([original])
    correction = observation(
        scope=scope,
        target_version="v2",
        assertion_version="v2",
        supersedes_id=original.record_id,
        score="0.5",
    )
    decision = TraceRecord.decision(
        scope=scope,
        target=correction.target,
        policy=decision_policy(assertion_version="v2"),
        execution_id=correction.execution_id,
        occurred_at=correction.occurred_at,
        parents=[correction],
    )
    mixed = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((decision_policy(assertion_version="v2"),)))

    emitted = await mixed.append_many([correction, decision])

    assert emitted == (correction, decision)
    assert not await mixed._is_lineage_head(scope, original.record_id)
    assert await mixed.current_decision(scope, decision.lineage) == decision


async def test_AC_audit_trace_record_9_batch_of_two_scopes_keeps_the_per_record_path(db):
    """AC-audit.trace-record.9: Batch of two scopes keeps the per record path."""
    repository = SqlTraceRecordRepository(db)
    first, second = observation(), observation()
    assert first.scope != second.scope

    assert await repository.append_many([first, second]) == (first, second)
    assert await repository.append_many([]) == ()


async def test_AC_audit_trace_record_9_batch_refuses_a_record_id_collision():
    """AC-audit.trace-record.9: Batch refuses a record id collision."""
    record = observation()
    forged = MagicMock(content_digest="0" * 64, record_id=record.record_id)

    with pytest.raises(TraceRecordPersistenceError, match="record id collision"):
        await SqlTraceRecordRepository(AsyncMock())._append_fresh_set((record, forged))

    db = AsyncMock()
    repository = SqlTraceRecordRepository(db)
    repository._cache[(record.scope, record.record_id)] = forged
    with pytest.raises(TraceRecordPersistenceError, match="record id collision"):
        await repository.append_many([record])


async def test_AC_audit_trace_record_9_batch_persistence_failure_is_explicit_and_forgets_the_set(db):
    """AC-audit.trace-record.9: Batch persistence failure is explicit and forgets the set."""
    policy = decision_policy()
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,)))
    scope = TraceScope.tenant(uuid4())
    records = _causal_set(scope, 2, policy=policy)

    with patch.object(db, "flush", AsyncMock(side_effect=SQLAlchemyError("insert refused"))):
        with pytest.raises(TraceRecordPersistenceError, match="insert refused"):
            await repository.append_many(records)

    for record in records:
        assert (scope, record.record_id) not in repository._cache
        assert (scope, record.record_id) not in repository._ancestry_cache
        assert (scope, record.record_id) not in repository._lineage_head_cache
    assert not repository._decision_head_cache


async def test_AC_audit_trace_record_9_head_read_names_lineages_in_chunks_and_detects_ambiguity(db):
    """AC-audit.trace-record.9: Head read names lineages in chunks and detects ambiguity."""
    policy = decision_policy()
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,)))
    scope = TraceScope.tenant(uuid4())
    records = _causal_set(scope, 5, policy=policy)
    await repository.append_many(records)
    decisions = [record for record in records if record.record_type.value == "decision"]
    absent = observation(scope=scope, target_id="absent").lineage

    with patch("src.audit.extension.trace_repository._READ_CHUNK_SIZE", 2), _Statements(db) as chunked:
        found = await repository.lineages_with_decision_head(scope, [*(d.lineage for d in decisions), absent])

    assert found == {decision.lineage for decision in decisions}
    assert len(chunked.texts) == 3  # six lineages in chunks of two
    assert await repository.lineages_with_decision_head(scope, []) == set()

    twin = MagicMock()
    twin.all.return_value = [("financial_fact", "x", "promotion", "y")] * 2
    ambiguous_db = AsyncMock()
    ambiguous_db.execute.return_value = twin
    with pytest.raises(TraceRecordPersistenceError, match="ambiguous physical"):
        await SqlTraceRecordRepository(ambiguous_db).lineages_with_decision_head(
            scope, [observation(scope=scope).lineage]
        )


async def test_AC_audit_trace_record_9_emitter_hands_a_set_to_a_batch_repository_and_one_by_one_to_others():
    """AC-audit.trace-record.9: Emitter hands a set to a batch repository and one by one to others."""
    first, second = observation(), observation()

    class BatchRepository:
        def __init__(self) -> None:
            self.sets: list[tuple] = []

        async def append_many(self, records):
            self.sets.append(tuple(records))
            return tuple(records)

    class SingleRepository:
        def __init__(self) -> None:
            self.appended: list = []

        async def append(self, record):
            self.appended.append(record)
            return record

    batch = BatchRepository()
    assert await TraceEmitter(batch).emit_many([first, second]) == (first, second)
    assert batch.sets == [(first, second)]

    single = SingleRepository()
    assert await TraceEmitter(single).emit_many([first, second]) == (first, second)
    assert single.appended == [first, second]

    # A mock repository answers any attribute. The emitter must not take a mock method for a batch method.
    mock_repository = MagicMock()
    mock_repository.append = AsyncMock(side_effect=lambda record: record)
    assert await TraceEmitter(mock_repository).emit_many([first]) == (first,)


async def test_AC_audit_trace_record_10_an_append_proves_head_ancestry_and_decision_head_without_a_statement(db):
    """AC-audit.trace-record.10: An append proves head ancestry and decision head without a statement."""
    policy = decision_policy()
    registry = TraceDecisionPolicyRegistry((policy,))
    repository = SqlTraceRecordRepository(db, registry)
    scope = TraceScope.tenant(uuid4())
    records = _causal_set(scope, 1, policy=policy)
    decision = records[1]
    await repository.append_many(records)

    with _Statements(db) as statements:
        assert await repository.get(scope, decision.record_id) == decision
        assert await repository._is_lineage_head(scope, decision.record_id)
        assert await repository._has_current_ancestry(scope, decision.record_id, frozenset())
        assert await repository._has_current_ancestry(scope, records[0].record_id, frozenset({decision.record_id}))
        assert await repository.current_decision(scope, decision.lineage) == decision
    assert statements.texts == []

    # The same proof holds for the single append.
    single = observation(scope=scope, target_id="single")
    await repository.append(single)
    with _Statements(db) as statements:
        assert await repository._has_current_ancestry(scope, single.record_id, frozenset())
    assert statements.texts == []


async def test_AC_audit_trace_record_10_a_correction_ends_the_proof_of_the_decision_head(db):
    """AC-audit.trace-record.10: A correction ends the proof of the decision head."""
    policy = decision_policy()
    registry = TraceDecisionPolicyRegistry((policy,))
    repository = SqlTraceRecordRepository(db, registry)
    scope = TraceScope.tenant(uuid4())
    parent, decision = _causal_set(scope, 1, policy=policy)
    await repository.append_many([parent, decision])
    assert await repository.current_decision(scope, decision.lineage) == decision

    correction = observation(
        scope=scope,
        target_id=parent.target.id,
        target_version="v2",
        assertion_version="v2",
        supersedes_id=parent.record_id,
        score="0.5",
    )
    await repository.append(correction)

    # The decision stands on a superseded parent: it is no longer current authority.
    assert await repository.current_decision(scope, decision.lineage) is None
    head = await repository.decision_head(scope, decision.lineage)
    assert head is not None and head.ancestry_current is False


async def test_AC_audit_trace_record_10_commit_and_rollback_end_the_proof(db):
    """AC-audit.trace-record.10: Commit and rollback end the proof."""
    policy = decision_policy()
    registry = TraceDecisionPolicyRegistry((policy,))
    repository = SqlTraceRecordRepository(db, registry)
    scope = TraceScope.tenant(uuid4())
    committed = _causal_set(scope, 1, policy=policy)
    await repository.append_many(committed)
    assert repository._cache and repository._decision_head_cache

    await db.commit()
    assert not repository._cache and not repository._ancestry_cache
    assert not repository._lineage_head_cache and not repository._decision_head_cache
    # The next read goes to the database and finds the committed rows.
    assert await repository.get(scope, committed[1].record_id) == committed[1]

    # A savepoint that rolls back removes its rows. The memo must not name them.
    savepoint = await db.begin_nested()
    rolled_back = [observation(scope=scope, target_id="rolled-back")]
    await repository.append_many(rolled_back)
    assert (scope, rolled_back[0].record_id) in repository._cache
    await savepoint.rollback()
    assert (scope, rolled_back[0].record_id) not in repository._cache
    assert await repository.get(scope, rolled_back[0].record_id) is None
    assert await repository.get(scope, committed[1].record_id) == committed[1]


async def test_AC_audit_trace_record_10_released_savepoint_keeps_the_proof(db):
    """AC-audit.trace-record.10: Released savepoint keeps the proof."""
    repository = SqlTraceRecordRepository(db)
    scope = TraceScope.tenant(uuid4())
    record = observation(scope=scope)
    async with db.begin_nested():
        await repository.append_many([record])
    assert (scope, record.record_id) in repository._cache

    with _Statements(db) as statements:
        assert await repository._has_current_ancestry(scope, record.record_id, frozenset())
    assert statements.texts == []
