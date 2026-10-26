"""Evidence graph adapters for source-to-ledger product workflows.

Layer-2 (DWD) lineage only: the source node is the ODS ``UploadedDocument`` and
the atomic fact is the ``AtomicTransaction``. The legacy extracted-record node
has no Layer-2 equivalent and has been dropped — ``UploadedDocument`` now links
directly to ``AtomicTransaction`` via the dual-write lineage.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.base.source_vocabulary import DocumentType
from src.extraction.base.types import extract_source_document_ids
from src.extraction.extension.evidence_lineage import EvidenceLineageService
from src.extraction.orm.evidence import EvidenceEdge, EvidenceNode
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction, AtomicTransactionSourceDocument
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import JournalEntry


class EvidenceGraphIntegrationService:
    """Small workflow adapters that dual-write business events into Evidence Graph."""

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
        """Materialize the ODS source artifact's current lifecycle facts."""
        if statement.id is None or uploaded_document.id is None:
            return None
        return await self.lineage.upsert_node(
            db,
            user_id=user_id,
            node_kind="source_document",
            entity_type="uploaded_document",
            entity_id=uploaded_document.id,
            properties={
                "document_type": uploaded_document.document_type.value,
                "file_hash": uploaded_document.file_hash,
                "original_filename": uploaded_document.original_filename,
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
        """Batch record ``UploadedDocument -> AtomicTransaction`` dual-write lineage.

        Eliminates per-transaction SELECT queries and per-item flush roundtrips during ingestion.
        """
        if uploaded_document.id is None or not atomic_transactions:
            return
        doc_type = document_type or uploaded_document.document_type
        doc_type_val = doc_type.value if doc_type is not None else uploaded_document.document_type.value

        valid_txns = [txn for txn in atomic_transactions if txn.id is not None]
        if not valid_txns:
            return

        txn_ids = [txn.id for txn in valid_txns]
        existing_links = set(
            (
                await db.execute(
                    select(AtomicTransactionSourceDocument.atomic_txn_id).where(
                        AtomicTransactionSourceDocument.atomic_txn_id.in_(txn_ids),
                        AtomicTransactionSourceDocument.uploaded_document_id == uploaded_document.id,
                    )
                )
            )
            .scalars()
            .all()
        )

        added_link = False
        for txn in valid_txns:
            if txn.id not in existing_links:
                db.add(
                    AtomicTransactionSourceDocument(
                        atomic_txn_id=txn.id,
                        uploaded_document_id=uploaded_document.id,
                        doc_type=doc_type_val,
                        ordinal=0,
                    )
                )
                existing_links.add(txn.id)
                added_link = True
        if added_link:
            await db.flush()

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

        existing_nodes = {
            node.entity_id: node
            for node in (
                await db.execute(
                    select(EvidenceNode)
                    .where(EvidenceNode.user_id == user_id)
                    .where(EvidenceNode.entity_type == "atomic_transaction")
                    .where(EvidenceNode.entity_id.in_(txn_ids))
                )
            )
            .scalars()
            .all()
        }

        created_node = False
        atomic_nodes: dict[UUID, EvidenceNode] = {}
        for txn in valid_txns:
            node = existing_nodes.get(txn.id)
            props = {
                "dedup_hash": txn.dedup_hash,
                "txn_date": txn.txn_date.isoformat(),
                "direction": txn.direction.value,
                "amount": str(txn.amount),
                "currency": txn.currency,
            }
            if node is None:
                node = EvidenceNode(
                    user_id=user_id,
                    node_kind="atomic_fact",
                    entity_type="atomic_transaction",
                    entity_id=txn.id,
                    properties=props,
                )
                db.add(node)
                created_node = True
            else:
                node.properties = props
            atomic_nodes[txn.id] = node

        if created_node:
            await db.flush()

        target_node_ids = [node.id for node in atomic_nodes.values()]
        existing_edges = set(
            (
                await db.execute(
                    select(EvidenceEdge.to_node_id).where(
                        EvidenceEdge.user_id == user_id,
                        EvidenceEdge.from_node_id == source_node.id,
                        EvidenceEdge.to_node_id.in_(target_node_ids),
                        EvidenceEdge.relation == "deduped_into",
                    )
                )
            )
            .scalars()
            .all()
        )

        added_edge = False
        for txn in valid_txns:
            atomic_node = atomic_nodes.get(txn.id)
            if atomic_node and atomic_node.id not in existing_edges:
                db.add(
                    EvidenceEdge(
                        user_id=user_id,
                        from_node_id=source_node.id,
                        to_node_id=atomic_node.id,
                        relation="deduped_into",
                        properties={
                            "dedup_hash": txn.dedup_hash,
                            "adapter": "layer2_dual_write",
                        },
                    )
                )
                existing_edges.add(atomic_node.id)
                added_edge = True
        if added_edge:
            await db.flush()

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
        await self.record_journal_postings_batch(
            db,
            user_id=user_id,
            postings=[(journal_entry, atomic_transaction)],
        )

    async def record_journal_postings_batch(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        postings: Sequence[tuple[JournalEntry, AtomicTransaction]],
    ) -> None:
        """Batch record ``AtomicTransaction -> JournalEntry -> JournalLine`` lineage.

        Eliminates per-transaction SELECT queries and per-item flush roundtrips.
        """
        if not postings:
            return

        all_doc_ids: list[UUID] = []
        doc_id_set: set[UUID] = set()
        for _, txn in postings:
            for doc_id in extract_source_document_ids(txn.source_documents):
                if doc_id not in doc_id_set:
                    doc_id_set.add(doc_id)
                    all_doc_ids.append(doc_id)

        docs_by_id: dict[UUID, UploadedDocument] = {}
        if all_doc_ids:
            rows = (
                (
                    await db.execute(
                        select(UploadedDocument)
                        .where(UploadedDocument.user_id == user_id)
                        .where(UploadedDocument.id.in_(all_doc_ids))
                    )
                )
                .scalars()
                .all()
            )
            docs_by_id = {doc.id: doc for doc in rows}

        needed_links: list[tuple[UUID, UUID, str]] = []
        for _, txn in postings:
            for doc_id in extract_source_document_ids(txn.source_documents):
                doc = docs_by_id.get(doc_id)
                if doc:
                    needed_links.append((txn.id, doc.id, doc.document_type.value))

        if needed_links:
            txn_ids = {link[0] for link in needed_links}
            doc_ids = {link[1] for link in needed_links}
            existing_links = {
                (row[0], row[1])
                for row in (
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
            added_link = False
            for txn_id, doc_id, doc_type_val in needed_links:
                if (txn_id, doc_id) not in existing_links:
                    db.add(
                        AtomicTransactionSourceDocument(
                            atomic_txn_id=txn_id,
                            uploaded_document_id=doc_id,
                            doc_type=doc_type_val,
                            ordinal=0,
                        )
                    )
                    existing_links.add((txn_id, doc_id))
                    added_link = True
            if added_link:
                await db.flush()

        node_specs: list[tuple[str, str, UUID, dict]] = []
        for doc in docs_by_id.values():
            node_specs.append(
                (
                    "source_document",
                    "uploaded_document",
                    doc.id,
                    {
                        "document_type": doc.document_type.value,
                        "original_filename": doc.original_filename,
                        "file_hash": doc.file_hash,
                    },
                )
            )
        for _, txn in postings:
            node_specs.append(
                (
                    "atomic_fact",
                    "atomic_transaction",
                    txn.id,
                    {
                        "dedup_hash": txn.dedup_hash,
                        "txn_date": txn.txn_date.isoformat(),
                        "direction": txn.direction.value,
                        "amount": str(txn.amount),
                        "currency": txn.currency,
                    },
                )
            )
        for entry, _ in postings:
            node_specs.append(
                (
                    "ledger_entry",
                    "journal_entry",
                    entry.id,
                    {
                        "source_type": entry.source_type.value,
                        "source_id": str(entry.source_id) if entry.source_id else None,
                        "status": entry.status.value,
                    },
                )
            )
            for line in entry.lines:
                node_specs.append(
                    (
                        "ledger_line",
                        "journal_line",
                        line.id,
                        {
                            "journal_entry_id": str(line.journal_entry_id),
                            "account_id": str(line.account_id),
                            "direction": line.direction.value,
                            "amount": str(line.amount),
                            "currency": line.currency,
                        },
                    )
                )

        all_entity_ids = [spec[2] for spec in node_specs]
        existing_nodes = (
            (
                await db.execute(
                    select(EvidenceNode)
                    .where(EvidenceNode.user_id == user_id)
                    .where(EvidenceNode.entity_id.in_(all_entity_ids))
                )
            )
            .scalars()
            .all()
        )
        nodes_by_key: dict[tuple[str, str, UUID], EvidenceNode] = {
            (node.node_kind, node.entity_type, node.entity_id): node for node in existing_nodes
        }

        created_node = False
        for node_kind, entity_type, entity_id, properties in node_specs:
            key = (node_kind, entity_type, entity_id)
            node = nodes_by_key.get(key)
            if node is None:
                node = EvidenceNode(
                    user_id=user_id,
                    node_kind=node_kind,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    properties=properties,
                )
                db.add(node)
                nodes_by_key[key] = node
                created_node = True
            elif properties is not None:
                node.properties = properties

        if created_node:
            await db.flush()

        edge_specs: list[tuple[EvidenceNode, EvidenceNode, str, dict]] = []
        for entry, txn in postings:
            atomic_node = nodes_by_key.get(("atomic_fact", "atomic_transaction", txn.id))
            if not atomic_node:
                continue

            for doc_id in extract_source_document_ids(txn.source_documents):
                source_node = nodes_by_key.get(("source_document", "uploaded_document", doc_id))
                if source_node:
                    edge_specs.append(
                        (
                            source_node,
                            atomic_node,
                            "deduped_into",
                            {
                                "dedup_hash": txn.dedup_hash,
                                "adapter": "layer2_dual_write",
                            },
                        )
                    )

            ledger_entry_node = nodes_by_key.get(("ledger_entry", "journal_entry", entry.id))
            if ledger_entry_node:
                edge_specs.append(
                    (
                        atomic_node,
                        ledger_entry_node,
                        "posted_as",
                        {"adapter": "journal_posting"},
                    )
                )
                for line in entry.lines:
                    line_node = nodes_by_key.get(("ledger_line", "journal_line", line.id))
                    if line_node:
                        edge_specs.append(
                            (
                                ledger_entry_node,
                                line_node,
                                "contains",
                                {"adapter": "journal_posting"},
                            )
                        )

        from_ids = {spec[0].id for spec in edge_specs}
        to_ids = {spec[1].id for spec in edge_specs}
        existing_edges = (
            (
                await db.execute(
                    select(EvidenceEdge)
                    .where(EvidenceEdge.user_id == user_id)
                    .where(EvidenceEdge.from_node_id.in_(from_ids))
                    .where(EvidenceEdge.to_node_id.in_(to_ids))
                )
            )
            .scalars()
            .all()
        )
        edges_by_key: dict[tuple[UUID, UUID, str], EvidenceEdge] = {
            (edge.from_node_id, edge.to_node_id, edge.relation): edge for edge in existing_edges
        }

        created_edge = False
        for from_node, to_node, relation, properties in edge_specs:
            edge_key = (from_node.id, to_node.id, relation)
            edge = edges_by_key.get(edge_key)
            if edge is None:
                edge = EvidenceEdge(
                    user_id=user_id,
                    from_node_id=from_node.id,
                    to_node_id=to_node.id,
                    relation=relation,
                    properties=properties,
                )
                db.add(edge)
                edges_by_key[edge_key] = edge
                created_edge = True
            elif properties is not None:
                edge.properties = properties

        if created_edge:
            await db.flush()
