"""SQLAlchemy adapter for typed-scope append-only TraceRecords."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import exists, func, select
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
            self._db.add_all(
                TraceRecordParentRow(
                    scope_kind=record.scope.kind,
                    scope_id=record.scope.id,
                    record_id=record.record_id,
                    parent_id=parent_id,
                )
                for parent_id in record.parent_ids
            )
            await self._db.flush()
            return record
        except TraceRecordPersistenceError:
            raise
        except (SQLAlchemyError, TraceRecordValidationError, RuntimeError) as exc:
            raise TraceRecordPersistenceError(f"TraceRecord append failed: {exc}") from exc

    async def get(self, scope: TraceScope, record_id: UUID) -> TraceRecord | None:
        try:
            return await self._get(scope, record_id, frozenset())
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
        return await self._restore(row, visiting | {record_id})

    async def current_decision(
        self,
        scope: TraceScope,
        lineage: TraceLineage,
    ) -> TraceRecord | None:
        try:
            head = await self._read_decision_head(scope, lineage)
            if head is None or not head.ancestry_current:
                return None
            return head.record
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
                raise TraceRecordPersistenceError(
                    "decision lineage already has a current authority head; the new decision must supersede it"
                )

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
        lineage_key = "\x1f".join(
            (
                record.scope.kind.value,
                record.scope.id,
                record.lineage.target_kind,
                record.lineage.target_id,
                record.lineage.assertion_kind,
                record.lineage.assertion_id,
            )
        )
        await self._db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lineage_key, 0))))

    async def _is_lineage_head(self, scope: TraceScope, record_id: UUID) -> bool:
        superseder = TraceRecordRow.__table__.alias("trace_superseder")
        return not bool(
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

    async def _has_current_ancestry(
        self,
        scope: TraceScope,
        record_id: UUID,
        visiting: frozenset[UUID],
    ) -> bool:
        if record_id in visiting:
            raise TraceRecordPersistenceError("TraceRecord parent graph contains a cycle")
        if not await self._is_lineage_head(scope, record_id):
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
            return not parent_ids
        if not parent_ids:
            return False
        next_visiting = visiting | {record_id}
        return all([await self._has_current_ancestry(scope, parent_id, next_visiting) for parent_id in parent_ids])

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
