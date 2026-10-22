"""SQLAlchemy adapter for typed-scope append-only TraceRecords."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterator, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import String, bindparam, event, exists, func, select, text, tuple_
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.base.trace import (
    TRACE_SCHEMA_VERSION,
    TraceAuthorityProfile,
    TraceDecisionPolicyRegistry,
    TraceLineage,
    TraceRecord,
    TraceRecordType,
    TraceRecordValidationError,
    TraceScope,
    VersionedTraceRef,
)
from src.audit.base.trace_repository import TraceDecisionHead, TraceRecordRepository
from src.audit.orm.trace_record import TraceRecordParentRow, TraceRecordRow
from src.audit.ratio import Ratio


class TraceRecordPersistenceError(RuntimeError):
    """A TraceRecord could not be validated or flushed in the caller's UoW."""


class SqlTraceRecordRepository(TraceRecordRepository):
    def __init__(
        self,
        db: AsyncSession,
        policies: TraceDecisionPolicyRegistry | None = None,
    ) -> None:
        self._db = db
        self._policies = policies or TraceDecisionPolicyRegistry()
        info = getattr(db, "info", None)
        if isinstance(info, dict):
            policy_records: dict[Any, dict[tuple[TraceScope, UUID], TraceRecord]] = info.setdefault(
                "_trace_record_cache_by_policies", {}
            )
            try:
                self._cache: dict[tuple[TraceScope, UUID], TraceRecord] = policy_records.setdefault(self._policies, {})
            except TypeError:
                self._cache = policy_records.setdefault(id(self._policies), {})
            self._lineage_head_cache: dict[tuple[TraceScope, UUID], bool] = info.setdefault(
                "_trace_lineage_head_cache", {}
            )
            self._ancestry_cache: dict[tuple[TraceScope, UUID], bool] = info.setdefault("_trace_ancestry_cache", {})
            self._decision_head_cache: dict[tuple[TraceScope, TraceLineage], UUID] = info.setdefault(
                "_trace_decision_head_cache", {}
            )
            _forget_caches_when_the_unit_of_work_ends(db, info)
        else:
            self._cache = {}
            self._lineage_head_cache = {}
            self._ancestry_cache = {}
            self._decision_head_cache = {}

    async def append(self, record: TraceRecord) -> TraceRecord:
        try:
            existing = await self.get(record.scope, record.record_id)
            if existing is not None:
                if existing.content_digest != record.content_digest:
                    raise TraceRecordPersistenceError("record id collision")
                return existing
            await self._lock_lineage(record)
            existing = await self.get(record.scope, record.record_id)
            if existing is not None:
                if existing.content_digest != record.content_digest:
                    raise TraceRecordPersistenceError("record id collision")
                return existing
            await self._validate_links(record)
            self._db.add(_row_from_record(record))
            await self._db.flush()
            if record.parent_ids:
                self._db.add_all(_parent_rows_from_record(record))
                await self._db.flush()
            self._remember_appended(record)
            return record
        except TraceRecordPersistenceError:
            raise
        except (SQLAlchemyError, TraceRecordValidationError, RuntimeError) as exc:
            raise TraceRecordPersistenceError(f"TraceRecord append failed: {exc}") from exc

    def _remember_appended(self, record: TraceRecord) -> None:
        """Record what an append proves, so that later reads in this unit of work need no query.

        The validation has shown that every parent is a current head with current ancestry.
        The lineage lock stays until the unit of work ends. So the new record is a head, and its
        ancestry is current. A superseding record ends the head state of the record it replaces.
        It also ends the ancestry of every descendant of that record, so the ancestry memo restarts.
        """
        key = (record.scope, record.record_id)
        self._cache[key] = record
        if record.supersedes_id is not None:
            self._lineage_head_cache.pop((record.scope, record.supersedes_id), None)
            self._ancestry_cache.clear()
        self._lineage_head_cache[key] = True
        self._ancestry_cache[key] = True
        if record.record_type is TraceRecordType.DECISION:
            self._decision_head_cache[(record.scope, record.lineage)] = record.record_id

    def _forget_appended(self, records: Sequence[TraceRecord]) -> None:
        """Undo ``_remember_appended`` for records that did not reach the database."""
        for record in records:
            key = (record.scope, record.record_id)
            self._cache.pop(key, None)
            self._lineage_head_cache.pop(key, None)
            self._ancestry_cache.pop(key, None)
            if self._decision_head_cache.get((record.scope, record.lineage)) == record.record_id:
                del self._decision_head_cache[(record.scope, record.lineage)]

    async def append_many(self, records: Sequence[TraceRecord]) -> tuple[TraceRecord, ...]:
        """Append an ordered causal set with a fixed number of statements.

        The checks are those of ``append``: content idempotence, one current head for each decision
        lineage, current parent heads, and replay of the decision policy. The set costs one lock
        statement, one existence read, one head read and two inserts, whatever its size. A set that
        holds a supersession keeps the per-record path. A supersession changes the heads that the
        later records of the set read.
        """
        batch = tuple(records)
        if not batch:
            return ()
        try:
            if len({record.scope for record in batch}) > 1 or any(record.supersedes_id is not None for record in batch):
                # Take the locks in key order first, as the fresh path does. Two writers of one set then
                # wait in the same order, whichever path each of them takes.
                await self._lock_lineages(batch)
                return tuple([await self.append(record) for record in batch])
            return await self._append_fresh_set(batch)
        except TraceRecordPersistenceError:
            raise
        except (SQLAlchemyError, TraceRecordValidationError, RuntimeError) as exc:
            raise TraceRecordPersistenceError(f"TraceRecord append failed: {exc}") from exc

    async def _append_fresh_set(self, batch: tuple[TraceRecord, ...]) -> tuple[TraceRecord, ...]:
        scope = batch[0].scope
        by_id: dict[UUID, TraceRecord] = {}
        for record in batch:
            earlier = by_id.setdefault(record.record_id, record)
            if earlier.content_digest != record.content_digest:
                raise TraceRecordPersistenceError("record id collision")
        await self._lock_lineages(by_id.values())

        unread = [record_id for record_id in by_id if (scope, record_id) not in self._cache]
        for ids in _chunks(unread, _READ_CHUNK_SIZE):
            rows = (
                (
                    await self._db.execute(
                        select(TraceRecordRow)
                        .where(TraceRecordRow.scope_kind == scope.kind)
                        .where(TraceRecordRow.scope_id == scope.id)
                        .where(TraceRecordRow.id.in_(ids))
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                try:
                    self._cache[(scope, row.id)] = await self._restore(row, frozenset({row.id}))
                except (SQLAlchemyError, TraceRecordValidationError, RuntimeError) as exc:
                    raise TraceRecordPersistenceError(f"TraceRecord read failed: {exc}") from exc
        for record_id, record in by_id.items():
            stored = self._cache.get((scope, record_id))
            if stored is not None and stored.content_digest != record.content_digest:
                raise TraceRecordPersistenceError("record id collision")
        new_records = [record for record_id, record in by_id.items() if (scope, record_id) not in self._cache]

        decision_lineages = [record.lineage for record in new_records if record.record_type is TraceRecordType.DECISION]
        forked = Counter(decision_lineages).most_common(1)
        if (forked and forked[0][1] > 1) or await self.lineages_with_decision_head(scope, decision_lineages):
            raise TraceRecordPersistenceError(_LINEAGE_FORK_MESSAGE)

        remembered: list[TraceRecord] = []
        try:
            for record in new_records:
                await self._validate_parents_and_policy(record)
                self._remember_appended(record)
                remembered.append(record)
            if new_records:
                self._db.add_all(_row_from_record(record) for record in new_records)
                await self._db.flush()
                parent_rows = [row for record in new_records for row in _parent_rows_from_record(record)]
                if parent_rows:
                    self._db.add_all(parent_rows)
                    await self._db.flush()
        except BaseException:
            self._forget_appended(remembered)
            raise
        return tuple(self._cache[(scope, record.record_id)] for record in batch)

    async def lineages_with_decision_head(
        self,
        scope: TraceScope,
        lineages: Collection[TraceLineage],
    ) -> set[TraceLineage]:
        """Return the lineages that hold a physical decision head, in one statement.

        The head does not need current ancestry. This is the read that ``append`` runs for each
        decision that does not supersede.
        """
        superseder = TraceRecordRow.__table__.alias("trace_superseder")
        lineage_columns = tuple_(
            TraceRecordRow.target_kind,
            TraceRecordRow.target_id,
            TraceRecordRow.assertion_kind,
            TraceRecordRow.assertion_id,
        )
        heads: Counter[TraceLineage] = Counter()
        for chunk in _chunks(sorted(set(lineages), key=_lineage_sort_key), _READ_CHUNK_SIZE):
            rows = (
                await self._db.execute(
                    select(
                        TraceRecordRow.target_kind,
                        TraceRecordRow.target_id,
                        TraceRecordRow.assertion_kind,
                        TraceRecordRow.assertion_id,
                    )
                    .where(TraceRecordRow.scope_kind == scope.kind)
                    .where(TraceRecordRow.scope_id == scope.id)
                    .where(TraceRecordRow.record_type == TraceRecordType.DECISION)
                    .where(
                        lineage_columns.in_(
                            [
                                (item.target_kind, item.target_id, item.assertion_kind, item.assertion_id)
                                for item in chunk
                            ]
                        )
                    )
                    .where(
                        ~exists(
                            select(1)
                            .where(superseder.c.scope_kind == scope.kind)
                            .where(superseder.c.scope_id == scope.id)
                            .where(superseder.c.supersedes_id == TraceRecordRow.id)
                        )
                    )
                )
            ).all()
            heads.update(TraceLineage(*row) for row in rows)
        if any(count > 1 for count in heads.values()):
            raise TraceRecordPersistenceError("ambiguous physical TraceRecord decision head")
        return set(heads)

    async def get(self, scope: TraceScope, record_id: UUID) -> TraceRecord | None:
        cached = self._cache.get((scope, record_id))
        if cached is not None:
            return cached
        try:
            record = await self._get(scope, record_id, frozenset())
            if record is not None:
                self._cache[(scope, record_id)] = record
            return record
        except (SQLAlchemyError, TraceRecordValidationError, RuntimeError) as exc:
            raise TraceRecordPersistenceError(f"TraceRecord read failed: {exc}") from exc

    async def _get(
        self,
        scope: TraceScope,
        record_id: UUID,
        visiting: frozenset[UUID],
    ) -> TraceRecord | None:
        if record_id in visiting:
            raise TraceRecordPersistenceError("TraceRecord parent graph contains a cycle")
        cached = self._cache.get((scope, record_id))
        if cached is not None:
            return cached
        row = (
            await self._db.execute(
                select(TraceRecordRow)
                .where(TraceRecordRow.scope_kind == scope.kind)
                .where(TraceRecordRow.scope_id == scope.id)
                .where(TraceRecordRow.id == record_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        record = await self._restore(row, visiting | {record_id})
        self._cache[(scope, record_id)] = record
        return record

    async def current_decision(
        self,
        scope: TraceScope,
        lineage: TraceLineage,
    ) -> TraceRecord | None:
        try:
            # This unit of work appended the head and still holds the lineage lock, so no other writer can
            # have replaced it. The record and its ancestry are in memory.
            appended_id = self._decision_head_cache.get((scope, lineage))
            appended = self._cache.get((scope, appended_id)) if appended_id is not None else None
            if appended is not None:
                return appended if await self._has_current_ancestry(scope, appended.record_id, frozenset()) else None
            row = await self._decision_head_row(scope, lineage)
            if row is None or not await self._has_current_ancestry(scope, row.id, frozenset()):
                return None
            return await self._restore(row, frozenset({row.id}))
        except TraceRecordPersistenceError:
            raise
        except (SQLAlchemyError, TraceRecordValidationError, RuntimeError) as exc:
            raise TraceRecordPersistenceError(f"TraceRecord current read failed: {exc}") from exc

    async def decision_head(
        self,
        scope: TraceScope,
        lineage: TraceLineage,
    ) -> TraceDecisionHead | None:
        try:
            return await self._read_decision_head(scope, lineage)
        except TraceRecordPersistenceError:
            raise
        except (SQLAlchemyError, TraceRecordValidationError, RuntimeError) as exc:
            raise TraceRecordPersistenceError(f"TraceRecord decision-head read failed: {exc}") from exc

    async def _read_decision_head(
        self,
        scope: TraceScope,
        lineage: TraceLineage,
    ) -> TraceDecisionHead | None:
        row = await self._decision_head_row(scope, lineage)
        if row is None:
            return None
        return TraceDecisionHead(
            record=await self._restore(row, frozenset({row.id})),
            ancestry_current=await self._has_current_ancestry(scope, row.id, frozenset()),
        )

    async def _decision_head_row(
        self,
        scope: TraceScope,
        lineage: TraceLineage,
    ) -> TraceRecordRow | None:
        superseder = TraceRecordRow.__table__.alias("trace_superseder")
        rows = (
            (
                await self._db.execute(
                    select(TraceRecordRow)
                    .where(TraceRecordRow.scope_kind == scope.kind)
                    .where(TraceRecordRow.scope_id == scope.id)
                    .where(TraceRecordRow.record_type == TraceRecordType.DECISION)
                    .where(TraceRecordRow.target_kind == lineage.target_kind)
                    .where(TraceRecordRow.target_id == lineage.target_id)
                    .where(TraceRecordRow.assertion_kind == lineage.assertion_kind)
                    .where(TraceRecordRow.assertion_id == lineage.assertion_id)
                    .where(
                        ~exists(
                            select(1)
                            .where(superseder.c.scope_kind == scope.kind)
                            .where(superseder.c.scope_id == scope.id)
                            .where(superseder.c.supersedes_id == TraceRecordRow.id)
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(rows) > 1:
            raise TraceRecordPersistenceError("ambiguous physical TraceRecord decision head")
        return rows[0] if rows else None

    async def _validate_links(self, record: TraceRecord) -> None:
        if record.supersedes_id is not None:
            previous = await self.get(record.scope, record.supersedes_id)
            if previous is None:
                raise TraceRecordPersistenceError("superseded record is missing or cross-scope")
            if previous.record_type is not record.record_type:
                raise TraceRecordPersistenceError("supersession cannot change TraceRecord type")
            if previous.lineage != record.lineage:
                raise TraceRecordPersistenceError("supersession cannot change stable TraceRecord lineage")
            if previous.target_class is not record.target_class:
                raise TraceRecordPersistenceError("supersession cannot change TraceRecord target class")
            if not await self._is_lineage_head(record.scope, previous.record_id):
                raise TraceRecordPersistenceError("superseded record is not a current lineage head")
        elif record.record_type is TraceRecordType.DECISION:
            physical_head = await self._decision_head_row(record.scope, record.lineage)
            if physical_head is not None:
                raise TraceRecordPersistenceError(_LINEAGE_FORK_MESSAGE)
        await self._validate_parents_and_policy(record)

    async def _validate_parents_and_policy(self, record: TraceRecord) -> None:
        """Check that every parent is a current head and that the policy replays to the same digest."""
        if record.record_type is TraceRecordType.OBSERVATION:
            if record.parent_ids:
                raise TraceRecordPersistenceError("observation cannot persist parent links")
            return

        parents: list[TraceRecord] = []
        for parent_id in record.parent_ids:
            parent = await self.get(record.scope, parent_id)
            if parent is None:
                raise TraceRecordPersistenceError("decision parent is missing or cross-scope")
            if not await self._has_current_ancestry(record.scope, parent.record_id, frozenset()):
                raise TraceRecordPersistenceError("every decision parent must be a current parent head")
            parents.append(parent)

        policy = self._policies.resolve(record.assertion)
        rebuilt = TraceRecord.decision(
            scope=record.scope,
            target=record.target,
            policy=policy,
            execution_id=record.execution_id,
            occurred_at=record.occurred_at,
            parents=parents,
            supersedes_id=record.supersedes_id,
        )
        if rebuilt.content_digest != record.content_digest:
            raise TraceRecordPersistenceError("decision policy replay does not match its digest")

    async def _lock_lineage(self, record: TraceRecord) -> None:
        await self._db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(_lineage_lock_key(record), 0))))

    async def _lock_lineages(self, records: Collection[TraceRecord]) -> None:
        """Take the lineage locks of a set in one statement, in key order.

        The key order is the same for every writer of a set, so two sets cannot wait on each other.
        """
        keys = sorted({_lineage_lock_key(record) for record in records})
        await self._db.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtextextended(lineage_key, 0)) "
                "FROM (SELECT lineage_key FROM unnest(CAST(:keys AS text[])) AS lineage(lineage_key) "
                "ORDER BY lineage_key OFFSET 0) AS ordered_keys"
            ).bindparams(bindparam("keys", keys, type_=ARRAY(String)))
        )

    async def _is_lineage_head(self, scope: TraceScope, record_id: UUID) -> bool:
        cache_key = (scope, record_id)
        if cache_key in self._lineage_head_cache:
            return self._lineage_head_cache[cache_key]
        superseder = TraceRecordRow.__table__.alias("trace_superseder")
        is_head = not bool(
            (
                await self._db.execute(
                    select(superseder.c.id)
                    .where(superseder.c.scope_kind == scope.kind)
                    .where(superseder.c.scope_id == scope.id)
                    .where(superseder.c.supersedes_id == record_id)
                    .limit(1)
                )
            ).scalar_one_or_none()
        )
        self._lineage_head_cache[cache_key] = is_head
        return is_head

    async def _has_current_ancestry(
        self,
        scope: TraceScope,
        record_id: UUID,
        visiting: frozenset[UUID],
    ) -> bool:
        if record_id in visiting:
            raise TraceRecordPersistenceError("TraceRecord parent graph contains a cycle")
        cache_key = (scope, record_id)
        # The memo holds a fact of the record itself, so it is valid at any depth of the walk. Without it
        # the walk repeats the reads of every ancestor for each descendant (#2612).
        if cache_key in self._ancestry_cache:
            return self._ancestry_cache[cache_key]
        if not await self._is_lineage_head(scope, record_id):
            if not visiting:
                self._ancestry_cache[cache_key] = False
            return False
        record_type = (
            await self._db.execute(
                select(TraceRecordRow.record_type)
                .where(TraceRecordRow.scope_kind == scope.kind)
                .where(TraceRecordRow.scope_id == scope.id)
                .where(TraceRecordRow.id == record_id)
            )
        ).scalar_one_or_none()
        if record_type is None:
            if not visiting:
                self._ancestry_cache[cache_key] = False
            return False
        parent_ids = tuple(
            (
                await self._db.execute(
                    select(TraceRecordParentRow.parent_id)
                    .where(TraceRecordParentRow.scope_kind == scope.kind)
                    .where(TraceRecordParentRow.scope_id == scope.id)
                    .where(TraceRecordParentRow.record_id == record_id)
                )
            ).scalars()
        )
        if record_type is TraceRecordType.OBSERVATION:
            is_valid = not parent_ids
            if not visiting:
                self._ancestry_cache[cache_key] = is_valid
            return is_valid
        if not parent_ids:
            if not visiting:
                self._ancestry_cache[cache_key] = False
            return False
        next_visiting = visiting | {record_id}
        has_ancestry = all(
            [await self._has_current_ancestry(scope, parent_id, next_visiting) for parent_id in parent_ids]
        )
        if not visiting or has_ancestry:
            self._ancestry_cache[cache_key] = has_ancestry
        return has_ancestry

    async def _restore(
        self,
        row: TraceRecordRow,
        visiting: frozenset[UUID],
    ) -> TraceRecord:
        if row.schema_version != TRACE_SCHEMA_VERSION:
            raise TraceRecordPersistenceError(
                f"unsupported persisted TraceRecord schema_version {row.schema_version!r}"
            )
        parent_ids = tuple(
            sorted(
                (
                    await self._db.execute(
                        select(TraceRecordParentRow.parent_id)
                        .where(TraceRecordParentRow.scope_kind == row.scope_kind)
                        .where(TraceRecordParentRow.scope_id == row.scope_id)
                        .where(TraceRecordParentRow.record_id == row.id)
                    )
                ).scalars(),
                key=str,
            )
        )
        if len(parent_ids) != row.parent_count:
            raise TraceRecordPersistenceError("persisted TraceRecord parent count mismatch")
        record = TraceRecord._construct(
            record_type=row.record_type,
            scope=TraceScope(kind=row.scope_kind, id=row.scope_id),
            target=VersionedTraceRef(
                kind=row.target_kind,
                id=row.target_id,
                version=row.target_version,
            ),
            target_class=row.target_class,
            assertion=VersionedTraceRef(
                kind=row.assertion_kind,
                id=row.assertion_id,
                version=row.assertion_version,
            ),
            authority=TraceAuthorityProfile(
                package=row.authority_package,
                tier=row.authority_tier,
                proof_kind=row.proof_kind,
                provenance=row.provenance,
                execution_stage=row.execution_stage,
                assertion_owner_digest=row.assertion_owner_digest,
                producer_version=row.producer_version,
            ),
            result=row.result,
            execution_id=row.execution_id,
            causality=row.causality,
            evidence_manifest_digest=row.evidence_manifest_digest,
            occurred_at=row.occurred_at,
            parent_ids=parent_ids,
            supersedes_id=row.supersedes_id,
            score=Ratio(row.score) if row.score is not None else None,
            reason_code=row.reason_code,
        )
        if record.record_id != row.id or record.content_digest != row.content_digest:
            raise TraceRecordPersistenceError("persisted TraceRecord digest mismatch")
        if record.record_type is TraceRecordType.DECISION:
            parents: list[TraceRecord] = []
            for parent_id in parent_ids:
                parent = await self._get(record.scope, parent_id, visiting)
                if parent is None:
                    raise TraceRecordPersistenceError("persisted decision parent is missing or cross-scope")
                parents.append(parent)
            policy = self._policies.resolve(record.assertion)
            replayed = TraceRecord.decision(
                scope=record.scope,
                target=record.target,
                policy=policy,
                execution_id=record.execution_id,
                occurred_at=record.occurred_at,
                parents=parents,
                supersedes_id=record.supersedes_id,
            )
            if replayed.content_digest != record.content_digest:
                raise TraceRecordPersistenceError("persisted decision policy replay does not match its digest")
        return record


_LINEAGE_FORK_MESSAGE = "decision lineage already has a current authority head; the new decision must supersede it"

#: A read names at most this many identifiers or lineages, so that its bind parameters stay below the driver limit.
_READ_CHUNK_SIZE = 1000


def _chunks(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _lineage_sort_key(lineage: TraceLineage) -> tuple[str, str, str, str]:
    return (lineage.target_kind, lineage.target_id, lineage.assertion_kind, lineage.assertion_id)


#: Keys of ``Session.info`` that hold what the repositories of one session know.
_CACHE_INFO_KEYS = (
    "_trace_record_cache_by_policies",
    "_trace_lineage_head_cache",
    "_trace_ancestry_cache",
    "_trace_decision_head_cache",
)
_CACHE_LISTENER_KEY = "_trace_cache_listener"


def _forget_caches_when_the_unit_of_work_ends(db: AsyncSession, info: dict[Any, Any]) -> None:
    """Drop what the repositories know when their proof ends.

    What an append proves holds while this unit of work holds the lineage locks. A commit releases
    them, and a rollback (also of a savepoint) removes the rows that the caches name. After either
    event the next read goes to the database.
    """
    sync_session = getattr(db, "sync_session", None)
    if sync_session is None or info.get(_CACHE_LISTENER_KEY):
        return

    def forget() -> None:
        for key in _CACHE_INFO_KEYS:
            cache = info.get(key)
            if not cache:
                continue
            if key == "_trace_record_cache_by_policies":
                for by_policy in cache.values():
                    by_policy.clear()
            else:
                cache.clear()

    def after_transaction_end(_session: Any, transaction: Any) -> None:
        if transaction.parent is None:
            forget()

    def after_soft_rollback(_session: Any, _previous: Any) -> None:
        forget()

    event.listen(sync_session, "after_transaction_end", after_transaction_end)
    event.listen(sync_session, "after_soft_rollback", after_soft_rollback)
    info[_CACHE_LISTENER_KEY] = True


def _lineage_lock_key(record: TraceRecord) -> str:
    """The key of the advisory lock that serializes the writers of one stable lineage."""
    return "\x1f".join(
        (
            record.scope.kind.value,
            record.scope.id,
            record.lineage.target_kind,
            record.lineage.target_id,
            record.lineage.assertion_kind,
            record.lineage.assertion_id,
        )
    )


def _parent_rows_from_record(record: TraceRecord) -> list[TraceRecordParentRow]:
    return [
        TraceRecordParentRow(
            scope_kind=record.scope.kind,
            scope_id=record.scope.id,
            record_id=record.record_id,
            parent_id=parent_id,
        )
        for parent_id in record.parent_ids
    ]


def _row_from_record(record: TraceRecord) -> TraceRecordRow:
    return TraceRecordRow(
        id=record.record_id,
        scope_kind=record.scope.kind,
        scope_id=record.scope.id,
        schema_version=record.schema_version,
        record_type=record.record_type,
        target_kind=record.target.kind,
        target_id=record.target.id,
        target_version=record.target.version,
        target_class=record.target_class,
        assertion_kind=record.assertion.kind,
        assertion_id=record.assertion.id,
        assertion_version=record.assertion.version,
        authority_package=record.authority.package,
        authority_tier=record.authority.tier,
        proof_kind=record.authority.proof_kind,
        provenance=record.authority.provenance,
        execution_stage=record.authority.execution_stage,
        assertion_owner_digest=record.authority.assertion_owner_digest,
        producer_version=record.authority.producer_version,
        result=record.result,
        execution_id=record.execution_id,
        causality=record.causality,
        evidence_manifest_digest=record.evidence_manifest_digest,
        parent_count=len(record.parent_ids),
        occurred_at=record.occurred_at,
        supersedes_id=record.supersedes_id,
        score=record.score.value if record.score is not None else None,
        reason_code=record.reason_code,
        content_digest=record.content_digest,
    )
