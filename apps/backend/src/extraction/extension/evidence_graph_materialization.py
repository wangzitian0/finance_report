"""Lazy Evidence Graph materialization and consistency checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from src.audit import STATEMENT_SOURCE_TYPES, JournalEntrySourceType
from src.extraction.extension.evidence_graph_integration import _ordered_source_doc_ids
from src.extraction.extension.evidence_lineage import EvidenceLineageService
from src.extraction.orm.evidence import EvidenceEdge, EvidenceNode
from src.extraction.orm.layer1 import UploadedDocument
from src.audit import JournalEntrySourceType
from src.extraction.orm.evidence import EvidenceEdge, EvidenceNode
from src.extraction.orm.layer2 import AtomicTransaction, AtomicTransactionSourceDocument
from src.ledger import JournalEntry, JournalLine
from src.models.statement_summary import StatementSummary

DEFAULT_MATERIALIZATION_WRITE_CAP = 25


@dataclass(frozen=True)
class EvidenceMaterializationBlocker:
    """Explicit blocker returned when deterministic graph materialization cannot proceed."""

    code: str
    message: str


@dataclass
class EvidenceMaterializationResult:
    """Summary of one bounded materialization attempt."""

    created_nodes: int = 0
    created_edges: int = 0
    blockers: list[EvidenceMaterializationBlocker] = field(default_factory=list)

    @property
    def has_writes(self) -> bool:
        return self.created_nodes > 0 or self.created_edges > 0

    @property
    def write_count(self) -> int:
        return self.created_nodes + self.created_edges


@dataclass(frozen=True)
class EvidenceConsistencyFinding:
    """Read-only consistency finding for Evidence Graph drift."""

    code: str
    severity: str
    entity_type: str
    entity_id: UUID
    message: str


@dataclass(frozen=True)
class EvidenceConsistencyReport:
    """Read-only drift report for operator checks."""

    findings: list[EvidenceConsistencyFinding]


class EvidenceGraphMaterializationService:
    """Repair missing graph projection rows from deterministic business relationships."""

    def __init__(self) -> None:
        self.lineage = EvidenceLineageService()

    async def materialize_for_entity(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        entity_type: str,
        entity_id: UUID,
        node_kind: str | None = None,
        max_writes: int = DEFAULT_MATERIALIZATION_WRITE_CAP,
    ) -> EvidenceMaterializationResult:
        """Materialize one local graph path for an owned entity identity."""
        result = EvidenceMaterializationResult()
        if max_writes <= 0:
            self._add_blocker(
                result,
                "materialization_write_cap_reached",
                "Request-time Evidence Graph materialization write cap was reached.",
            )
            return result

        if entity_type == "journal_line":
            await self._materialize_journal_line(db, user_id=user_id, line_id=entity_id, result=result, cap=max_writes)
        elif entity_type == "journal_entry":
            await self._materialize_journal_entry(
                db, user_id=user_id, entry_id=entity_id, result=result, cap=max_writes
            )
        elif entity_type == "uploaded_document":
            await self._materialize_uploaded_document(
                db, user_id=user_id, document_id=entity_id, result=result, cap=max_writes
            )
        elif entity_type == "atomic_transaction":
            await self._materialize_atomic_transaction(
                db, user_id=user_id, atomic_id=entity_id, result=result, cap=max_writes
            )
        else:
            self._add_blocker(result, "unsupported_provenance", f"Unsupported Evidence Graph entity: {entity_type}.")
        return result

    async def detect_consistency_drift(
        self,
        db: AsyncSession,
        *,
        user_id: UUID | None = None,
    ) -> EvidenceConsistencyReport:
        """Return a read-only consistency report without repairing graph rows."""
        findings: list[EvidenceConsistencyFinding] = []
        await self._detect_missing_journal_line_nodes(db, user_id=user_id, findings=findings)
        await self._detect_orphan_nodes(db, user_id=user_id, findings=findings)
        await self._detect_dangling_edges(db, user_id=user_id, findings=findings)
        await self._detect_cross_user_edges(db, user_id=user_id, findings=findings)
        return EvidenceConsistencyReport(findings=findings)

    async def _materialize_journal_line(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        line_id: UUID,
        result: EvidenceMaterializationResult,
        cap: int,
    ) -> None:
        row = (
            await db.execute(
                select(JournalLine, JournalEntry)
                .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
                .where(JournalLine.id == line_id)
                .options(selectinload(JournalLine.journal_entry))
                .limit(1)
            )
        ).first()
        if row is None:
            self._add_blocker(result, "entity_missing", "Journal line does not exist.")
            return
        line, entry = row
        if entry.user_id != user_id:
            self._add_blocker(result, "cross_user_lineage_blocked", "Journal line belongs to a different user.")
            return
        entry = (
            await db.execute(
                select(JournalEntry)
                .where(JournalEntry.id == line.journal_entry_id)
                .options(selectinload(JournalEntry.lines))
                .limit(1)
            )
        ).scalar_one()
        await self._materialize_journal_entry(db, user_id=user_id, entry=entry, result=result, cap=cap)

    async def _materialize_journal_entry(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        result: EvidenceMaterializationResult,
        cap: int,
        entry_id: UUID | None = None,
        entry: JournalEntry | None = None,
    ) -> EvidenceNode | None:
        if entry is None:
            entry = (
                await db.execute(
                    select(JournalEntry)
                    .where(JournalEntry.id == entry_id)
                    .options(selectinload(JournalEntry.lines))
                    .limit(1)
                )
            ).scalar_one_or_none()
        if entry is None:
            self._add_blocker(result, "entity_missing", "Journal entry does not exist.")
            return None
        if entry.user_id != user_id:
            self._add_blocker(result, "cross_user_lineage_blocked", "Journal entry belongs to a different user.")
            return None

        ledger_entry = await self._upsert_node(
            db,
            user_id=user_id,
            node_kind="ledger_entry",
            entity_type="journal_entry",
            entity_id=entry.id,
            properties={
                "source_type": entry.source_type.value,
                "source_id": str(entry.source_id) if entry.source_id else None,
                "status": entry.status.value,
            },
            result=result,
            cap=cap,
        )
        if ledger_entry is None:
            return None

        for line in entry.lines:
            ledger_line = await self._upsert_node(
                db,
                user_id=user_id,
                node_kind="ledger_line",
                entity_type="journal_line",
                entity_id=line.id,
                properties={
                    "journal_entry_id": str(line.journal_entry_id),
                    "account_id": str(line.account_id),
                    "direction": line.direction.value,
                    "amount": str(line.amount),
                    "currency": line.currency,
                },
                result=result,
                cap=cap,
            )
            if ledger_line is None:
                return ledger_entry
            edge = await self._upsert_edge(
                db,
                user_id=user_id,
                from_node_id=ledger_entry.id,
                to_node_id=ledger_line.id,
                relation="contains",
                properties={"adapter": "lazy_materialization"},
                result=result,
                cap=cap,
            )
            if edge is None:
                return ledger_entry

        await self._materialize_entry_source(
            db, user_id=user_id, entry=entry, ledger_entry=ledger_entry, result=result, cap=cap
        )
        return ledger_entry

    async def _materialize_entry_source(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        entry: JournalEntry,
        ledger_entry: EvidenceNode,
        result: EvidenceMaterializationResult,
        cap: int,
    ) -> None:
        if entry.source_id is None:
            return

        atomic = await self._get_owned_atomic_transaction(db, user_id=user_id, atomic_id=entry.source_id)
        if atomic is not None:
            atomic_node = await self._materialize_atomic_transaction(
                db,
                user_id=user_id,
                atomic=atomic,
                result=result,
                cap=cap,
            )
            if atomic_node is not None:
                await self._upsert_edge(
                    db,
                    user_id=user_id,
                    from_node_id=atomic_node.id,
                    to_node_id=ledger_entry.id,
                    relation="posted_as",
                    properties={"adapter": "lazy_materialization"},
                    result=result,
                    cap=cap,
                )
            return

        if entry.source_type in STATEMENT_SOURCE_TYPES:
            self._add_blocker(result, "entity_missing", "Journal entry source_id does not resolve to an owned source.")
        elif entry.source_type not in {
            JournalEntrySourceType.MANUAL,
            JournalEntrySourceType.SYSTEM,
            JournalEntrySourceType.FX_REVALUATION,
        }:
            self._add_blocker(
                result,
                "unsupported_provenance",
                f"Unsupported journal source type for Evidence Graph materialization: {entry.source_type.value}.",
            )

    async def _materialize_uploaded_document(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        result: EvidenceMaterializationResult,
        cap: int,
        document_id: UUID | None = None,
        document: UploadedDocument | None = None,
    ) -> EvidenceNode | None:
        if document is None:
            document = (
                await db.execute(
                    select(UploadedDocument)
                    .where(UploadedDocument.user_id == user_id)
                    .where(UploadedDocument.id == document_id)
                    .limit(1)
                )
            ).scalar_one_or_none()
        if document is None:
            self._add_blocker(result, "entity_missing", "Uploaded document does not exist for this user.")
            return None
        return await self._upsert_node(
            db,
            user_id=user_id,
            node_kind="source_document",
            entity_type="uploaded_document",
            entity_id=document.id,
            properties={
                "document_type": document.document_type.value,
                "original_filename": document.original_filename,
                "file_hash": document.file_hash,
            },
            result=result,
            cap=cap,
        )

    async def _materialize_atomic_transaction(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        result: EvidenceMaterializationResult,
        cap: int,
        atomic_id: UUID | None = None,
        atomic: AtomicTransaction | None = None,
    ) -> EvidenceNode | None:
        if atomic is None:
            atomic = await self._get_owned_atomic_transaction(db, user_id=user_id, atomic_id=atomic_id)
        if atomic is None:
            self._add_blocker(result, "entity_missing", "Atomic transaction does not exist for this user.")
            return None
        atomic_node = await self._upsert_node(
            db,
            user_id=user_id,
            node_kind="atomic_fact",
            entity_type="atomic_transaction",
            entity_id=atomic.id,
            properties={
                "dedup_hash": atomic.dedup_hash,
                "txn_date": atomic.txn_date.isoformat(),
                "direction": atomic.direction.value,
                "amount": str(atomic.amount),
                "currency": atomic.currency,
            },
            result=result,
            cap=cap,
        )
        if atomic_node is None:
            return None
        await self._materialize_source_documents(
            db, user_id=user_id, atomic=atomic, atomic_node=atomic_node, result=result, cap=cap
        )
        return atomic_node

    async def _materialize_source_documents(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        atomic: AtomicTransaction,
        atomic_node: EvidenceNode,
        result: EvidenceMaterializationResult,
        cap: int,
    ) -> None:
        """Materialize ``UploadedDocument -> AtomicTransaction`` dual-write edges.

        Resolves the source documents recorded on the atomic transaction
        (``source_documents``) and links each one straight to the atomic fact. The
        legacy extracted-record middle node is dropped.
        """
        linked_documents = (
            (
                await db.execute(
                    select(UploadedDocument)
                    .join(
                        AtomicTransactionSourceDocument,
                        AtomicTransactionSourceDocument.uploaded_document_id == UploadedDocument.id,
                    )
                    .where(AtomicTransactionSourceDocument.atomic_txn_id == atomic.id)
                    .where(UploadedDocument.user_id == user_id)
                    .order_by(
                        AtomicTransactionSourceDocument.ordinal.asc(),
                        AtomicTransactionSourceDocument.uploaded_document_id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        if linked_documents:
            for document in linked_documents:
                source = await self._materialize_uploaded_document(
                    db, user_id=user_id, document=document, result=result, cap=cap
                )
                if source is None:
                    return
                edge = await self._upsert_edge(
                    db,
                    user_id=user_id,
                    from_node_id=source.id,
                    to_node_id=atomic_node.id,
                    relation="deduped_into",
                    properties={"dedup_hash": atomic.dedup_hash, "adapter": "lazy_materialization"},
                    result=result,
                    cap=cap,
                )
                if edge is None:
                    return
            return

        doc_ids = _ordered_source_doc_ids(atomic.source_documents)
        if not doc_ids:
            return
        documents = (
            (
                await db.execute(
                    select(UploadedDocument)
                    .where(UploadedDocument.user_id == user_id)
                    .where(UploadedDocument.id.in_(doc_ids))
                )
            )
            .scalars()
            .all()
        )
        by_id = {document.id: document for document in documents}
        for doc_id in doc_ids:
            document = by_id.get(doc_id)
            if document is None:
                self._add_blocker(
                    result,
                    "entity_missing",
                    "Legacy atomic source document does not resolve to an owned uploaded document.",
                )
                continue
            source = await self._materialize_uploaded_document(
                db, user_id=user_id, document=document, result=result, cap=cap
            )
            if source is None:
                return
            edge = await self._upsert_edge(
                db,
                user_id=user_id,
                from_node_id=source.id,
                to_node_id=atomic_node.id,
                relation="deduped_into",
                properties={"dedup_hash": atomic.dedup_hash, "adapter": "lazy_materialization"},
                result=result,
                cap=cap,
            )
            if edge is None:
                return

    async def _upsert_node(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        node_kind: str,
        entity_type: str,
        entity_id: UUID,
        properties: dict,
        result: EvidenceMaterializationResult,
        cap: int,
    ) -> EvidenceNode | None:
        existing = await self.lineage.get_node_for_entity(
            db,
            user_id=user_id,
            node_kind=node_kind,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        if existing is None and result.write_count >= cap:
            self._add_blocker(
                result,
                "materialization_write_cap_reached",
                "Request-time Evidence Graph materialization write cap was reached.",
            )
            return None
        node = await self.lineage.upsert_node(
            db,
            user_id=user_id,
            node_kind=node_kind,
            entity_type=entity_type,
            entity_id=entity_id,
            properties=properties,
        )
        if existing is None:
            result.created_nodes += 1
        return node

    async def _upsert_edge(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        from_node_id: UUID,
        to_node_id: UUID,
        relation: str,
        properties: dict,
        result: EvidenceMaterializationResult,
        cap: int,
    ) -> EvidenceEdge | None:
        existing = (
            await db.execute(
                select(EvidenceEdge)
                .where(EvidenceEdge.user_id == user_id)
                .where(EvidenceEdge.from_node_id == from_node_id)
                .where(EvidenceEdge.to_node_id == to_node_id)
                .where(EvidenceEdge.relation == relation)
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is None and result.write_count >= cap:
            self._add_blocker(
                result,
                "materialization_write_cap_reached",
                "Request-time Evidence Graph materialization write cap was reached.",
            )
            return None
        edge = await self.lineage.upsert_edge(
            db,
            user_id=user_id,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            relation=relation,
            properties=properties,
        )
        if existing is None:
            result.created_edges += 1
        return edge

    async def _get_owned_atomic_transaction(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        atomic_id: UUID | None,
    ) -> AtomicTransaction | None:
        if atomic_id is None:
            return None
        return (
            await db.execute(
                select(AtomicTransaction)
                .where(AtomicTransaction.user_id == user_id)
                .where(AtomicTransaction.id == atomic_id)
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _detect_missing_journal_line_nodes(
        self,
        db: AsyncSession,
        *,
        user_id: UUID | None,
        findings: list[EvidenceConsistencyFinding],
    ) -> None:
        query = select(JournalLine.id).join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        if user_id is not None:
            query = query.where(JournalEntry.user_id == user_id)
        query = query.where(
            ~exists()
            .where(EvidenceNode.user_id == JournalEntry.user_id)
            .where(EvidenceNode.node_kind == "ledger_line")
            .where(EvidenceNode.entity_type == "journal_line")
            .where(EvidenceNode.entity_id == JournalLine.id)
        )
        for line_id in (await db.execute(query.limit(100))).scalars().all():
            findings.append(
                EvidenceConsistencyFinding(
                    code="graph_node_missing",
                    severity="medium",
                    entity_type="journal_line",
                    entity_id=line_id,
                    message="Journal line exists without a ledger_line Evidence Graph node.",
                )
            )

    async def _detect_orphan_nodes(
        self,
        db: AsyncSession,
        *,
        user_id: UUID | None,
        findings: list[EvidenceConsistencyFinding],
    ) -> None:
        query = select(EvidenceNode)
        if user_id is not None:
            query = query.where(EvidenceNode.user_id == user_id)
        for node in (await db.execute(query.limit(200))).scalars().all():
            if await self._business_entity_exists(db, node=node):
                continue
            findings.append(
                EvidenceConsistencyFinding(
                    code="orphan_graph_node",
                    severity="high",
                    entity_type=node.entity_type,
                    entity_id=node.entity_id,
                    message="Evidence Graph node points to a missing or cross-user business entity.",
                )
            )

    async def _detect_cross_user_edges(
        self,
        db: AsyncSession,
        *,
        user_id: UUID | None,
        findings: list[EvidenceConsistencyFinding],
    ) -> None:
        from_node = aliased(EvidenceNode)
        to_node = aliased(EvidenceNode)
        query = (
            select(EvidenceEdge, from_node, to_node)
            .join(from_node, EvidenceEdge.from_node_id == from_node.id)
            .join(to_node, EvidenceEdge.to_node_id == to_node.id)
        )
        if user_id is not None:
            query = query.where(EvidenceEdge.user_id == user_id)
        rows = (await db.execute(query.limit(200))).all()
        for edge, source, target in rows:
            if edge.user_id == source.user_id == target.user_id:
                continue
            findings.append(
                EvidenceConsistencyFinding(
                    code="cross_user_lineage_blocked",
                    severity="high",
                    entity_type="evidence_edge",
                    entity_id=edge.id,
                    message="Evidence Graph edge user does not match both endpoint users.",
                )
            )

    async def _detect_dangling_edges(
        self,
        db: AsyncSession,
        *,
        user_id: UUID | None,
        findings: list[EvidenceConsistencyFinding],
    ) -> None:
        from_node = aliased(EvidenceNode)
        to_node = aliased(EvidenceNode)
        query = (
            select(EvidenceEdge, from_node.id, to_node.id)
            .outerjoin(from_node, EvidenceEdge.from_node_id == from_node.id)
            .outerjoin(to_node, EvidenceEdge.to_node_id == to_node.id)
        )
        if user_id is not None:
            query = query.where(EvidenceEdge.user_id == user_id)
        rows = (await db.execute(query.limit(200))).all()
        for edge, from_node_id, to_node_id in rows:
            if from_node_id is not None and to_node_id is not None:
                continue
            findings.append(
                EvidenceConsistencyFinding(
                    code="dangling_edge",
                    severity="high",
                    entity_type="evidence_edge",
                    entity_id=edge.id,
                    message="Evidence Graph edge points to a missing endpoint node.",
                )
            )

    async def _business_entity_exists(self, db: AsyncSession, *, node: EvidenceNode) -> bool:
        if node.entity_type == "journal_line":
            row = (
                await db.execute(
                    select(JournalLine.id)
                    .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
                    .where(JournalLine.id == node.entity_id)
                    .where(JournalEntry.user_id == node.user_id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            return row is not None
        if node.entity_type == "journal_entry":
            row = (
                await db.execute(
                    select(JournalEntry.id)
                    .where(JournalEntry.id == node.entity_id)
                    .where(JournalEntry.user_id == node.user_id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            return row is not None
        if node.entity_type == "statement_summary":
            row = (
                await db.execute(
                    select(StatementSummary.id)
                    .where(StatementSummary.id == node.entity_id)
                    .where(StatementSummary.user_id == node.user_id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            return row is not None
        if node.entity_type == "uploaded_document":
            row = (
                await db.execute(
                    select(UploadedDocument.id)
                    .where(UploadedDocument.id == node.entity_id)
                    .where(UploadedDocument.user_id == node.user_id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            return row is not None
        if node.entity_type == "atomic_transaction":
            return (
                await self._get_owned_atomic_transaction(db, user_id=node.user_id, atomic_id=node.entity_id) is not None
            )
        return True

    @staticmethod
    def _add_blocker(result: EvidenceMaterializationResult, code: str, message: str) -> None:
        blocker = EvidenceMaterializationBlocker(code=code, message=message)
        if blocker not in result.blockers:
            result.blockers.append(blocker)
