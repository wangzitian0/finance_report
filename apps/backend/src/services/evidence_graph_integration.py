"""Evidence graph adapters for source-to-ledger product workflows."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.evidence import EvidenceNode
from src.models.journal import JournalEntry, JournalLine
from src.models.layer1 import DocumentType, UploadedDocument
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.statement import BankStatement, BankStatementTransaction
from src.services.deduplication import DeduplicationService
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
        statement: BankStatement,
    ) -> EvidenceNode | None:
        """Record the uploaded BankStatement as a source document node."""
        if statement.id is None:
            return None
        return await self.lineage.upsert_node(
            db,
            user_id=user_id,
            node_kind="source_document",
            entity_type="bank_statement",
            entity_id=statement.id,
            properties={
                "file_hash": statement.file_hash,
                "original_filename": statement.original_filename,
                "institution": statement.institution,
            },
        )

    async def record_statement_parse(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        statement: BankStatement,
        transactions: list[BankStatementTransaction],
    ) -> None:
        """Record BankStatement -> BankStatementTransaction parse lineage."""
        source_node = await self.record_statement_upload(db, user_id=user_id, statement=statement)
        if source_node is None:
            return
        for transaction in transactions:
            if transaction.id is None:
                continue
            extracted_node = await self._upsert_statement_transaction_node(
                db,
                user_id=user_id,
                transaction=transaction,
            )
            await self.lineage.upsert_edge(
                db,
                user_id=user_id,
                from_node_id=source_node.id,
                to_node_id=extracted_node.id,
                relation="parsed_into",
                properties={"adapter": "statement_parse"},
            )

    async def record_statement_layer2_lineage(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        statement: BankStatement,
        transactions: list[BankStatementTransaction],
    ) -> None:
        """Backfill parse-time Layer 2 edges once statement transactions have database UUIDs."""
        result = await db.execute(
            select(UploadedDocument)
            .where(UploadedDocument.user_id == user_id)
            .where(UploadedDocument.file_hash == statement.file_hash)
            .order_by(UploadedDocument.created_at.desc(), UploadedDocument.id.desc())
            .limit(1)
        )
        uploaded_document = result.scalar_one_or_none()
        if uploaded_document is None:
            return

        for transaction in transactions:
            atomic_transaction = await self._find_atomic_transaction_for_bank_txn(
                db,
                user_id=user_id,
                transaction=transaction,
            )
            if atomic_transaction is None:
                continue
            await self.record_layer2_dual_write(
                db,
                user_id=user_id,
                uploaded_document=uploaded_document,
                source_transaction=transaction,
                atomic_transaction=atomic_transaction,
                document_type=uploaded_document.document_type,
            )

    async def record_layer2_dual_write(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        uploaded_document: UploadedDocument,
        source_transaction: BankStatementTransaction,
        atomic_transaction: AtomicTransaction,
        document_type: DocumentType,
    ) -> None:
        """Record UploadedDocument -> BankStatementTransaction -> AtomicTransaction lineage."""
        statement = await self._resolve_statement(db, source_transaction)
        if statement is not None:
            await self.record_statement_parse(
                db,
                user_id=user_id,
                statement=statement,
                transactions=[source_transaction],
            )
        source_node = await self.lineage.upsert_node(
            db,
            user_id=user_id,
            node_kind="source_document",
            entity_type="uploaded_document",
            entity_id=uploaded_document.id,
            properties={
                "document_type": document_type.value,
                "original_filename": uploaded_document.original_filename,
                "file_hash": uploaded_document.file_hash,
            },
        )

        txn_id = source_transaction.id
        if txn_id is None:
            return

        extracted_node = await self._upsert_statement_transaction_node(
            db,
            user_id=user_id,
            transaction=source_transaction,
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
            to_node_id=extracted_node.id,
            relation="parsed_into",
            properties={"adapter": "layer2_dual_write"},
        )
        await self.lineage.upsert_edge(
            db,
            user_id=user_id,
            from_node_id=extracted_node.id,
            to_node_id=atomic_node.id,
            relation="deduped_into",
            properties={"dedup_hash": atomic_transaction.dedup_hash},
        )

    async def record_journal_posting(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        source_transaction: BankStatementTransaction,
        journal_entry: JournalEntry,
        atomic_transaction: AtomicTransaction | None = None,
    ) -> None:
        """Record BankStatementTransaction/AtomicTransaction -> JournalEntry -> JournalLine lineage."""
        extracted_node = await self._upsert_statement_transaction_node(
            db,
            user_id=user_id,
            transaction=source_transaction,
        )
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
            from_node_id=extracted_node.id,
            to_node_id=ledger_entry_node.id,
            relation="posted_as",
            properties={"adapter": "journal_posting"},
        )

        atomic_transaction = atomic_transaction or await self._find_atomic_transaction_for_bank_txn(
            db,
            user_id=user_id,
            transaction=source_transaction,
        )
        if atomic_transaction is not None:
            atomic_node = await self._upsert_atomic_transaction_node(
                db,
                user_id=user_id,
                atomic_transaction=atomic_transaction,
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

    async def _upsert_statement_transaction_node(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        transaction: BankStatementTransaction,
    ) -> EvidenceNode:
        statement = await self._resolve_statement(db, transaction)
        properties = {
            "statement_id": str(transaction.statement_id),
            "txn_date": transaction.txn_date.isoformat(),
            "direction": transaction.direction,
            "amount": str(transaction.amount),
            "currency": transaction.currency or (statement.currency if statement else None),
            "reference": transaction.reference,
        }
        return await self.lineage.upsert_node(
            db,
            user_id=user_id,
            node_kind="extracted_record",
            entity_type="bank_statement_transaction",
            entity_id=transaction.id,
            properties=properties,
        )

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

    async def _find_atomic_transaction_for_bank_txn(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        transaction: BankStatementTransaction,
    ) -> AtomicTransaction | None:
        direction = TransactionDirection.IN if transaction.direction == "IN" else TransactionDirection.OUT
        dedup_hash = DeduplicationService.calculate_transaction_hash(
            user_id,
            transaction.txn_date,
            transaction.amount,
            direction,
            transaction.description,
            transaction.reference,
        )
        result = await db.execute(
            select(AtomicTransaction)
            .where(AtomicTransaction.user_id == user_id)
            .where(AtomicTransaction.dedup_hash == dedup_hash)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _resolve_statement(
        self,
        db: AsyncSession,
        transaction: BankStatementTransaction,
    ) -> BankStatement | None:
        state = sa_inspect(transaction)
        if "statement" not in state.unloaded and transaction.statement is not None:
            return transaction.statement
        result = await db.execute(select(BankStatement).where(BankStatement.id == transaction.statement_id).limit(1))
        return result.scalar_one_or_none()
