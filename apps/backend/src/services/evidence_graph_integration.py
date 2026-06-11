"""Evidence graph adapters for source-to-ledger product workflows.

Layer-2 (DWD) lineage only: the source node is the ODS ``UploadedDocument`` and
the atomic fact is the ``AtomicTransaction``. The legacy extracted-record node
has no Layer-2 equivalent and has been dropped — ``UploadedDocument`` now links
directly to ``AtomicTransaction`` via the dual-write lineage.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.evidence import EvidenceNode
from src.models.journal import JournalEntry, JournalLine
from src.models.layer1 import DocumentType, UploadedDocument
from src.models.layer2 import AtomicTransaction
from src.models.statement_summary import StatementSummary
from src.services.evidence_lineage import EvidenceLineageService


class EvidenceGraphIntegrationService:
    """Small workflow adapters that dual-write business events into Evidence Graph."""

    def __init__(self) -> None:
        self.lineage = EvidenceLineageService()

    async def record_statement_upload(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        statement: StatementSummary,
    ) -> EvidenceNode | None:
        """Record the confirmed ``StatementSummary`` envelope as a source document node.

        The DWD conform does not carry ``original_filename`` (an ODS field); callers
        may attach it transiently for lineage display only.
        """
        if statement.id is None:
            return None
        return await self.lineage.upsert_node(
            db,
            user_id=user_id,
            node_kind="source_document",
            entity_type="statement_summary",
            entity_id=statement.id,
            properties={
                "file_hash": statement.file_hash,
                "original_filename": getattr(statement, "original_filename", None),
                "institution": statement.institution,
            },
        )

    async def record_layer2_dual_write(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        uploaded_document: UploadedDocument,
        atomic_transaction: AtomicTransaction,
        document_type: DocumentType | None = None,
    ) -> None:
        """Record ``UploadedDocument -> AtomicTransaction`` dual-write lineage.

        Layer-2 lineage skips the legacy extracted-record node entirely: the
        uploaded source document deduplicates straight into the atomic fact.
        """
        if uploaded_document.id is None or atomic_transaction.id is None:
            return
        doc_type = document_type or uploaded_document.document_type
        source_node = await self.lineage.upsert_node(
            db,
            user_id=user_id,
            node_kind="source_document",
            entity_type="uploaded_document",
            entity_id=uploaded_document.id,
            properties={
                "document_type": doc_type.value if doc_type is not None else None,
                "original_filename": uploaded_document.original_filename,
                "file_hash": uploaded_document.file_hash,
            },
        )
        atomic_node = await self._upsert_atomic_transaction_node(
            db,
            user_id=user_id,
            atomic_transaction=atomic_transaction,
        )
        await self.lineage.upsert_edge(
            db,
            user_id=user_id,
            from_node_id=source_node.id,
            to_node_id=atomic_node.id,
            relation="deduped_into",
            properties={
                "dedup_hash": atomic_transaction.dedup_hash,
                "adapter": "layer2_dual_write",
            },
        )

    async def record_journal_posting(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        journal_entry: JournalEntry,
        atomic_transaction: AtomicTransaction,
    ) -> None:
        """Record ``AtomicTransaction -> JournalEntry -> JournalLine`` lineage.

        Also backfills the ``UploadedDocument -> AtomicTransaction`` dual-write edges
        for each source document recorded on the atomic transaction.
        """
        atomic_node = await self._upsert_atomic_transaction_node(
            db,
            user_id=user_id,
            atomic_transaction=atomic_transaction,
        )
        await self._record_source_documents(db, user_id=user_id, atomic_transaction=atomic_transaction)

        ledger_entry_node = await self.lineage.upsert_node(
            db,
            user_id=user_id,
            node_kind="ledger_entry",
            entity_type="journal_entry",
            entity_id=journal_entry.id,
            properties={
                "source_type": journal_entry.source_type.value,
                "source_id": str(journal_entry.source_id) if journal_entry.source_id else None,
                "status": journal_entry.status.value,
            },
        )
        await self.lineage.upsert_edge(
            db,
            user_id=user_id,
            from_node_id=atomic_node.id,
            to_node_id=ledger_entry_node.id,
            relation="posted_as",
            properties={"adapter": "journal_posting"},
        )

        for line in journal_entry.lines:
            await self._record_journal_line(
                db,
                user_id=user_id,
                journal_line=line,
                ledger_entry_node_id=ledger_entry_node.id,
            )

    async def _record_journal_line(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        journal_line: JournalLine,
        ledger_entry_node_id: UUID,
    ) -> None:
        ledger_line_node = await self.lineage.upsert_node(
            db,
            user_id=user_id,
            node_kind="ledger_line",
            entity_type="journal_line",
            entity_id=journal_line.id,
            properties={
                "journal_entry_id": str(journal_line.journal_entry_id),
                "account_id": str(journal_line.account_id),
                "direction": journal_line.direction.value,
                "amount": str(journal_line.amount),
                "currency": journal_line.currency,
            },
        )
        await self.lineage.upsert_edge(
            db,
            user_id=user_id,
            from_node_id=ledger_entry_node_id,
            to_node_id=ledger_line_node.id,
            relation="contains",
            properties={"adapter": "journal_posting"},
        )

    async def _record_source_documents(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        atomic_transaction: AtomicTransaction,
    ) -> None:
        """Backfill ``UploadedDocument -> AtomicTransaction`` edges from source_documents."""
        for document in await self._resolve_source_documents(
            db, user_id=user_id, atomic_transaction=atomic_transaction
        ):
            await self.record_layer2_dual_write(
                db,
                user_id=user_id,
                uploaded_document=document,
                atomic_transaction=atomic_transaction,
                document_type=document.document_type,
            )

    async def _resolve_source_documents(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        atomic_transaction: AtomicTransaction,
    ) -> list[UploadedDocument]:
        """Resolve the owning ``UploadedDocument`` rows from ``source_documents``."""
        doc_ids = _ordered_source_doc_ids(atomic_transaction.source_documents)
        if not doc_ids:
            return []
        rows = (
            await db.execute(
                select(UploadedDocument)
                .where(UploadedDocument.user_id == user_id)
                .where(UploadedDocument.id.in_(doc_ids))
            )
        ).scalars().all()
        by_id = {document.id: document for document in rows}
        return [by_id[doc_id] for doc_id in doc_ids if doc_id in by_id]

    async def _upsert_atomic_transaction_node(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        atomic_transaction: AtomicTransaction,
    ) -> EvidenceNode:
        return await self.lineage.upsert_node(
            db,
            user_id=user_id,
            node_kind="atomic_fact",
            entity_type="atomic_transaction",
            entity_id=atomic_transaction.id,
            properties={
                "dedup_hash": atomic_transaction.dedup_hash,
                "txn_date": atomic_transaction.txn_date.isoformat(),
                "direction": atomic_transaction.direction.value,
                "amount": str(atomic_transaction.amount),
                "currency": atomic_transaction.currency,
            },
        )


def _ordered_source_doc_ids(source_documents: object) -> list[UUID]:
    """Extract source ``UploadedDocument`` ids, in order, from ``source_documents``.

    Accepts the canonical list form (``[{"doc_id": ..., "doc_type": ...}]``) and a
    ``{"documents": [...]}`` wrapper. Invalid UUID strings are skipped so they never
    raise during query binding.
    """
    if isinstance(source_documents, dict):
        source_documents = source_documents.get("documents", [])
    if not isinstance(source_documents, list):
        return []

    ordered: list[UUID] = []
    seen: set[UUID] = set()
    for entry in source_documents:
        if not isinstance(entry, dict):
            continue
        raw = entry.get("doc_id")
        if not raw:
            continue
        try:
            doc_id = UUID(str(raw))
        except (ValueError, TypeError):
            continue
        if doc_id not in seen:
            seen.add(doc_id)
            ordered.append(doc_id)
    return ordered
