"""Evidence graph adapters for source-to-ledger product workflows."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.base.source_vocabulary import DocumentType
from src.extraction.base.types import extract_source_document_ids
from src.extraction.extension.evidence_lineage import (
    EvidenceLineageService,
    doc_node_props,
    entry_node_props,
    line_node_props,
    txn_node_props,
    upsert_edges_batch,
    upsert_nodes_batch,
)
from src.extraction.orm.evidence import EvidenceNode
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction, AtomicTransactionSourceDocument
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import JournalEntry


async def _ensure_txn_doc_links(
    db: AsyncSession,
    links: Sequence[tuple[UUID, UUID, str]],
) -> None:
    if not links:
        return
    txn_ids = {t for t, _, _ in links}
    doc_ids = {d for _, d, _ in links}
    existing = {
        (r[0], r[1])
        for r in (
            await db.execute(
                select(
                    AtomicTransactionSourceDocument.atomic_txn_id,
                    AtomicTransactionSourceDocument.uploaded_document_id,
                ).where(
                    AtomicTransactionSourceDocument.atomic_txn_id.in_(txn_ids),
                    AtomicTransactionSourceDocument.uploaded_document_id.in_(doc_ids),
                )
            )
        ).all()
    }
    added = False
    for txn_id, doc_id, doc_type_val in links:
        if (txn_id, doc_id) not in existing:
            db.add(
                AtomicTransactionSourceDocument(
                    atomic_txn_id=txn_id,
                    uploaded_document_id=doc_id,
                    doc_type=doc_type_val,
                    ordinal=0,
                )
            )
            existing.add((txn_id, doc_id))
            added = True
    if added:
        await db.flush()


class EvidenceGraphIntegrationService:
    """Workflow adapters that dual-write business events into the Evidence Graph."""

    def __init__(self) -> None:
        self.lineage = EvidenceLineageService()

    async def record_statement_source(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        statement: StatementSummary,
        uploaded_document: UploadedDocument,
    ) -> EvidenceNode | None:
        if statement.id is None or uploaded_document.id is None:
            return None
        return await self.lineage.upsert_node(
            db,
            user_id=user_id,
            node_kind="source_document",
            entity_type="uploaded_document",
            entity_id=uploaded_document.id,
            properties={
                **doc_node_props(uploaded_document),
                "status": uploaded_document.status.value,
                "institution": statement.institution,
            },
        )

    async def record_layer2_dual_writes_batch(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        uploaded_document: UploadedDocument,
        atomic_transactions: Sequence[AtomicTransaction],
        document_type: DocumentType | None = None,
    ) -> None:
        if uploaded_document.id is None or not atomic_transactions:
            return
        valid_txns = [txn for txn in atomic_transactions if txn.id is not None]
        if not valid_txns:
            return

        doc_type = document_type or uploaded_document.document_type
        doc_type_val = doc_type.value if doc_type is not None else uploaded_document.document_type.value
        await _ensure_txn_doc_links(db, [(txn.id, uploaded_document.id, doc_type_val) for txn in valid_txns])

        source_node = await self.lineage.upsert_node(
            db,
            user_id=user_id,
            node_kind="source_document",
            entity_type="uploaded_document",
            entity_id=uploaded_document.id,
            properties=doc_node_props(uploaded_document, doc_type_value=doc_type.value if doc_type is not None else None),
        )
        nodes_by_key = await upsert_nodes_batch(
            db,
            user_id=user_id,
            specs=[("atomic_fact", "atomic_transaction", txn.id, txn_node_props(txn)) for txn in valid_txns],
        )
        await upsert_edges_batch(
            db,
            user_id=user_id,
            specs=[
                (
                    source_node,
                    nodes_by_key[("atomic_fact", "atomic_transaction", txn.id)],
                    "deduped_into",
                    {"dedup_hash": txn.dedup_hash, "adapter": "layer2_dual_write"},
                )
                for txn in valid_txns
                if ("atomic_fact", "atomic_transaction", txn.id) in nodes_by_key
            ],
        )

    async def record_journal_posting(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        journal_entry: JournalEntry,
        atomic_transaction: AtomicTransaction,
    ) -> None:
        await self.record_journal_postings_batch(db, user_id=user_id, postings=[(journal_entry, atomic_transaction)])

    async def record_journal_postings_batch(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        postings: Sequence[tuple[JournalEntry, AtomicTransaction]],
    ) -> None:
        if not postings:
            return

        doc_ids = list(dict.fromkeys(did for _, txn in postings for did in extract_source_document_ids(txn.source_documents)))
        docs_by_id = (
            {
                doc.id: doc
                for doc in (
                    await db.execute(
                        select(UploadedDocument).where(
                            UploadedDocument.user_id == user_id, UploadedDocument.id.in_(doc_ids)
                        )
                    )
                ).scalars().all()
            }
            if doc_ids
            else {}
        )

        await _ensure_txn_doc_links(
            db,
            [
                (txn.id, doc.id, doc.document_type.value)
                for _, txn in postings
                for did in extract_source_document_ids(txn.source_documents)
                if (doc := docs_by_id.get(did)) is not None
            ],
        )

        node_specs = [
            *(("source_document", "uploaded_document", doc.id, doc_node_props(doc)) for doc in docs_by_id.values()),
            *(("atomic_fact", "atomic_transaction", txn.id, txn_node_props(txn)) for _, txn in postings),
        ]
        for entry, _ in postings:
            node_specs.append(("ledger_entry", "journal_entry", entry.id, entry_node_props(entry)))
            for line in entry.lines:
                node_specs.append(("ledger_line", "journal_line", line.id, line_node_props(line)))

        nodes_by_key = await upsert_nodes_batch(db, user_id=user_id, specs=node_specs)

        edge_specs: list[tuple[EvidenceNode, EvidenceNode, str, dict]] = []
        for entry, txn in postings:
            atomic_node = nodes_by_key.get(("atomic_fact", "atomic_transaction", txn.id))
            if not atomic_node:
                continue
            for did in extract_source_document_ids(txn.source_documents):
                if src_node := nodes_by_key.get(("source_document", "uploaded_document", did)):
                    edge_specs.append(
                        (src_node, atomic_node, "deduped_into", {"dedup_hash": txn.dedup_hash, "adapter": "layer2_dual_write"})
                    )
            if entry_node := nodes_by_key.get(("ledger_entry", "journal_entry", entry.id)):
                edge_specs.append((atomic_node, entry_node, "posted_as", {"adapter": "journal_posting"}))
                for line in entry.lines:
                    if line_node := nodes_by_key.get(("ledger_line", "journal_line", line.id)):
                        edge_specs.append((entry_node, line_node, "contains", {"adapter": "journal_posting"}))

        await upsert_edges_batch(db, user_id=user_id, specs=edge_specs)
