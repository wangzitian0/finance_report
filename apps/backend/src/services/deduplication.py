import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.logger import get_logger
from src.models.layer1 import DocumentType, UploadedDocument
from src.models.layer2 import AtomicPosition, AtomicTransaction, TransactionDirection
from src.models.statement import BankStatement, BankStatementTransaction
from src.services.statement_summary import sync_statement_summary

logger = get_logger(__name__)


def _decimal_key(value: Decimal) -> str:
    """Canonical, scale-independent string for a Decimal used in dedup hashing.

    ``Decimal('50')``, ``Decimal('50.00')`` and ``Decimal('50.000')`` all map to
    ``'50'`` so values differing only in scale hash identically.
    """
    return format(value.normalize(), "f")


class DeduplicationService:
    """Service for managing Layer 2 deduplicated records with hash-based upsert logic."""

    @staticmethod
    def calculate_transaction_hash(
        user_id: UUID,
        txn_date: date,
        amount: Decimal,
        direction: TransactionDirection,
        description: str,
        reference: str | None = None,
        balance_after: Decimal | None = None,
    ) -> str:
        """Calculate deduplication hash for atomic transaction.

        Hash = SHA256(user_id|date|amount|direction|description|reference|balance_after)

        ``balance_after`` (the statement running balance) is included so two real,
        otherwise-identical transactions (same date/amount/direction/description, no
        reference) stay distinct — their running balances differ. Genuine duplicate
        extractions share the same running balance and still collapse. When the
        source has no running balance the field is empty and behaviour is unchanged.

        Decimal amounts are canonicalized (``Decimal('50')`` and ``Decimal('50.00')``
        hash identically) so values that differ only in scale do not break dedup.
        """
        components = [
            str(user_id),
            txn_date.isoformat(),
            _decimal_key(amount),
            direction.value,
            description.strip().lower(),
            reference or "",
            _decimal_key(balance_after) if balance_after is not None else "",
        ]
        hash_input = "|".join(components).encode("utf-8")
        return hashlib.sha256(hash_input).hexdigest()

    @staticmethod
    def calculate_position_hash(
        user_id: UUID,
        snapshot_date: date,
        asset_identifier: str,
        broker: str | None = None,
    ) -> str:
        """Calculate deduplication hash for atomic position.

        Hash = SHA256(user_id|snapshot_date|asset_identifier|broker)
        """
        components = [
            str(user_id),
            snapshot_date.isoformat(),
            asset_identifier.strip().lower(),
            broker.strip().lower() if broker else "",
        ]
        hash_input = "|".join(components).encode("utf-8")
        return hashlib.sha256(hash_input).hexdigest()

    async def upsert_atomic_transaction(
        self,
        db: AsyncSession,
        user_id: UUID,
        txn_date: date,
        amount: Decimal,
        direction: TransactionDirection,
        description: str,
        currency: str,
        source_doc_id: UUID,
        source_doc_type: DocumentType,
        reference: str | None = None,
        balance_after: Decimal | None = None,
    ) -> AtomicTransaction:
        """Upsert atomic transaction with deduplication.

        If dedup_hash exists -> Append to source_documents array
        If dedup_hash new -> Insert new record
        """
        dedup_hash = self.calculate_transaction_hash(
            user_id, txn_date, amount, direction, description, reference, balance_after
        )

        stmt = select(AtomicTransaction).where(
            AtomicTransaction.user_id == user_id,
            AtomicTransaction.dedup_hash == dedup_hash,
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        source_doc = {
            "doc_id": str(source_doc_id),
            "doc_type": source_doc_type.value,
        }

        if existing:
            source_docs = existing.source_documents
            if not isinstance(source_docs, list):
                source_docs = []

            if source_doc not in source_docs:
                source_docs.append(source_doc)
                existing.source_documents = source_docs
                await db.flush()

            logger.info(
                f"Appended source document to existing atomic transaction {existing.id}",
                extra={
                    "dedup_hash": dedup_hash,
                    "source_doc_id": str(source_doc_id),
                    "source_doc_type": source_doc_type.value,
                },
            )
            return existing

        new_txn = AtomicTransaction(
            user_id=user_id,
            txn_date=txn_date,
            amount=amount,
            direction=direction,
            description=description,
            reference=reference,
            currency=currency,
            dedup_hash=dedup_hash,
            source_documents=[source_doc],
        )
        db.add(new_txn)
        await db.flush()

        logger.info(
            f"Created new atomic transaction {new_txn.id}",
            extra={
                "dedup_hash": dedup_hash,
                "txn_date": str(txn_date),
                "amount": str(amount),
                "direction": direction.value,
            },
        )
        return new_txn

    async def upsert_atomic_position(
        self,
        db: AsyncSession,
        user_id: UUID,
        snapshot_date: date,
        asset_identifier: str,
        quantity: Decimal,
        market_value: Decimal,
        currency: str,
        source_doc_id: UUID,
        source_doc_type: DocumentType,
        broker: str | None = None,
    ) -> AtomicPosition:
        """Upsert atomic position with deduplication.

        If dedup_hash exists -> Append to source_documents array
        If dedup_hash new -> Insert new record
        """
        dedup_hash = self.calculate_position_hash(user_id, snapshot_date, asset_identifier, broker)

        stmt = select(AtomicPosition).where(
            AtomicPosition.user_id == user_id,
            AtomicPosition.dedup_hash == dedup_hash,
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        source_doc = {
            "doc_id": str(source_doc_id),
            "doc_type": source_doc_type.value,
        }

        if existing:
            source_docs = existing.source_documents
            if not isinstance(source_docs, list):
                source_docs = []

            if source_doc not in source_docs:
                source_docs.append(source_doc)
                existing.source_documents = source_docs
                await db.flush()

            logger.info(
                f"Appended source document to existing atomic position {existing.id}",
                extra={
                    "dedup_hash": dedup_hash,
                    "source_doc_id": str(source_doc_id),
                    "source_doc_type": source_doc_type.value,
                },
            )
            return existing

        new_pos = AtomicPosition(
            user_id=user_id,
            snapshot_date=snapshot_date,
            asset_identifier=asset_identifier,
            broker=broker,
            quantity=quantity,
            market_value=market_value,
            currency=currency,
            dedup_hash=dedup_hash,
            source_documents=[source_doc],
        )
        db.add(new_pos)
        await db.flush()

        logger.info(
            f"Created new atomic position {new_pos.id}",
            extra={
                "dedup_hash": dedup_hash,
                "snapshot_date": str(snapshot_date),
                "asset_identifier": asset_identifier,
                "quantity": str(quantity),
            },
        )
        return new_pos

    async def create_uploaded_document(
        self,
        db: AsyncSession,
        user_id: UUID,
        file_path: str,
        file_hash: str,
        original_filename: str,
        document_type: DocumentType,
        extraction_metadata: dict[str, Any] | None = None,
    ) -> UploadedDocument:
        """Create Layer 1 document metadata record.

        Raises IntegrityError if file_hash already exists for this user.
        """
        doc = UploadedDocument(
            user_id=user_id,
            file_path=file_path,
            file_hash=file_hash,
            original_filename=original_filename,
            document_type=document_type,
            extraction_metadata=extraction_metadata,
        )
        db.add(doc)
        await db.flush()

        logger.info(
            f"Created uploaded document {doc.id}",
            extra={
                "file_hash": file_hash,
                "document_type": document_type.value,
                "original_filename": original_filename,
            },
        )
        return doc


async def dual_write_layer2(
    db: Any,
    user_id: UUID,
    file_path: Path | None,
    file_hash: str,
    original_filename: str,
    institution: str,
    transactions: list[BankStatementTransaction],
    document_type: DocumentType | None = None,
    extraction_metadata: dict[str, Any] | None = None,
) -> None:
    """Write parsed data to Layer 1/2 tables (Phase 2 dual write).

    Precondition: transactions must have .statement relationship eager-loaded
    for txn.statement.currency access.

    Raises RuntimeError on non-IntegrityError failures.
    IntegrityError (duplicate upload) is silently ignored.
    """
    from sqlalchemy.exc import IntegrityError

    dedup_service = DeduplicationService()

    doc_type_map = {
        "dbs": DocumentType.BANK_STATEMENT,
        "ocbc": DocumentType.BANK_STATEMENT,
        "standard chartered": DocumentType.BANK_STATEMENT,
        "citibank": DocumentType.BANK_STATEMENT,
        "uob": DocumentType.BANK_STATEMENT,
        "posb": DocumentType.BANK_STATEMENT,
    }
    doc_type = document_type or doc_type_map.get(institution.lower(), DocumentType.BANK_STATEMENT)

    try:
        uploaded_doc = await dedup_service.create_uploaded_document(
            db=db,
            user_id=user_id,
            file_path=str(file_path) if file_path else file_hash,
            file_hash=file_hash,
            original_filename=original_filename,
            document_type=doc_type,
            extraction_metadata=extraction_metadata,
        )

        layer2_count = 0
        from src.services.evidence_graph_integration import EvidenceGraphIntegrationService

        evidence_graph = EvidenceGraphIntegrationService()
        for txn in transactions:
            direction_map = {"IN": TransactionDirection.IN, "OUT": TransactionDirection.OUT}
            l2_direction = direction_map.get(txn.direction, TransactionDirection.IN)

            atomic_txn = await dedup_service.upsert_atomic_transaction(
                db=db,
                user_id=user_id,
                txn_date=txn.txn_date,
                amount=txn.amount,
                direction=l2_direction,
                description=txn.description,
                currency=txn.statement.currency or "SGD",
                source_doc_id=uploaded_doc.id,
                source_doc_type=doc_type,
                reference=txn.reference,
                balance_after=txn.balance_after,
            )
            await evidence_graph.record_layer2_dual_write(
                db,
                user_id=user_id,
                uploaded_document=uploaded_doc,
                source_transaction=txn,
                atomic_transaction=atomic_txn,
                document_type=doc_type,
            )
            layer2_count += 1

        logger.info(
            "Dual write to Layer 2 completed",
            uploaded_doc_id=str(uploaded_doc.id),
            layer2_transactions=layer2_count,
            layer0_transactions=len(transactions),
        )

    except IntegrityError:
        # Duplicate upload - acceptable silent failure
        logger.warning(
            "Dual write skipped - document already exists",
            file_hash=file_hash,
            user_id=str(user_id),
        )
    except Exception as e:
        # All other errors are CRITICAL - must be visible to user
        logger.error(
            "Dual write to Layer 2 FAILED - data integrity compromised",
            error=str(e),
            error_type=type(e).__name__,
            user_id=str(user_id),
            file_hash=file_hash,
            layer0_transactions=len(transactions),
        )
        # Re-raise to ensure caller knows dual-write failed
        raise RuntimeError(f"Failed to write to Layer 2: {e}") from e


BACKFILL_STATEMENT_BATCH_SIZE = 200


async def backfill_atomic_transactions_from_statements(
    db: AsyncSession,
    user_id: UUID | None = None,
    *,
    batch_size: int = BACKFILL_STATEMENT_BATCH_SIZE,
) -> dict[str, int]:
    """Idempotently populate Layer 1/2 from existing Layer 0 statements (EPIC-011 Stage 2a).

    For every ``BankStatement`` (optionally scoped to ``user_id``) this ensures a
    Layer 1 ``UploadedDocument`` exists and every ``BankStatementTransaction`` has a
    Layer 2 ``AtomicTransaction``. This backfills historical data that predates the
    Stage 1 dual-write activation, so the Layer-2 read path has full coverage before
    ``ENABLE_4_LAYER_READ`` is turned on.

    Safe to re-run: ``UploadedDocument`` is keyed by ``(user_id, file_hash)`` and
    ``AtomicTransaction`` by ``(user_id, dedup_hash)``, so re-execution upserts
    rather than duplicates.

    Statements are streamed in batches of ``batch_size`` (loading each batch's
    transactions on demand) so production-sized datasets do not load every
    statement and transaction into memory at once.

    Returns counts: ``statements_scanned``, ``documents_created``,
    ``atomic_transactions_upserted``.
    """
    dedup_service = DeduplicationService()

    # Fetch statement IDs only (lightweight), then hydrate one bounded batch at a
    # time. This keeps peak memory proportional to ``batch_size`` rather than the
    # full statement/transaction set.
    id_query = select(BankStatement.id)
    if user_id is not None:
        id_query = id_query.where(BankStatement.user_id == user_id)
    id_query = id_query.order_by(BankStatement.created_at)
    statement_ids = (await db.execute(id_query)).scalars().all()

    statements_scanned = 0
    documents_created = 0
    atomic_upserted = 0
    summaries_synced = 0

    for offset in range(0, len(statement_ids), batch_size):
        batch_ids = statement_ids[offset : offset + batch_size]
        batch = (
            (
                await db.execute(
                    select(BankStatement)
                    .where(BankStatement.id.in_(batch_ids))
                    .options(selectinload(BankStatement.transactions))
                    .order_by(BankStatement.created_at)
                )
            )
            .scalars()
            .all()
        )

        for stmt in batch:
            statements_scanned += 1
            owner_id = stmt.user_id  # BankStatement.user_id is NOT NULL

            doc_type = (
                DocumentType.BROKERAGE_STATEMENT
                if (stmt.extraction_metadata or {}).get("extraction_payload")
                else DocumentType.BANK_STATEMENT
            )

            existing_doc = (
                await db.execute(
                    select(UploadedDocument).where(
                        UploadedDocument.user_id == owner_id,
                        UploadedDocument.file_hash == stmt.file_hash,
                    )
                )
            ).scalar_one_or_none()

            if existing_doc is None:
                try:
                    # SAVEPOINT so a duplicate-insert race only rolls back this one
                    # document, never the statements already backfilled in this run.
                    async with db.begin_nested():
                        existing_doc = await dedup_service.create_uploaded_document(
                            db=db,
                            user_id=owner_id,
                            file_path=stmt.file_path or stmt.file_hash,
                            file_hash=stmt.file_hash,
                            original_filename=stmt.original_filename or "unknown",
                            document_type=doc_type,
                            extraction_metadata=stmt.extraction_metadata,
                        )
                    documents_created += 1
                except IntegrityError:  # pragma: no cover - concurrent-writer race, not deterministically unit-testable
                    # Concurrent writer created it first; reload the existing row.
                    existing_doc = (
                        await db.execute(
                            select(UploadedDocument).where(
                                UploadedDocument.user_id == owner_id,
                                UploadedDocument.file_hash == stmt.file_hash,
                            )
                        )
                    ).scalar_one()

            for txn in stmt.transactions:
                direction_map = {"IN": TransactionDirection.IN, "OUT": TransactionDirection.OUT}
                l2_direction = direction_map.get(txn.direction, TransactionDirection.IN)
                await dedup_service.upsert_atomic_transaction(
                    db=db,
                    user_id=owner_id,
                    txn_date=txn.txn_date,
                    amount=txn.amount,
                    direction=l2_direction,
                    description=txn.description,
                    # Match the live dual-write path (`dual_write_layer2`), which
                    # sources currency from the statement, so backfilled rows are
                    # identical to organically dual-written ones.
                    currency=stmt.currency or "SGD",
                    source_doc_id=existing_doc.id,
                    source_doc_type=doc_type,
                    reference=txn.reference,
                    balance_after=txn.balance_after,
                )
                atomic_upserted += 1

            # Project the confirmed statement envelope (custody account, period,
            # balances, review state) into the StatementSummary conform.
            await sync_statement_summary(db, stmt)
            summaries_synced += 1

    logger.info(
        "Layer 2 backfill completed",
        extra={
            "statements_scanned": statements_scanned,
            "documents_created": documents_created,
            "atomic_transactions_upserted": atomic_upserted,
            "statement_summaries_synced": summaries_synced,
            "user_scope": str(user_id) if user_id else "all",
        },
    )

    return {
        "statements_scanned": statements_scanned,
        "documents_created": documents_created,
        "atomic_transactions_upserted": atomic_upserted,
        "statement_summaries_synced": summaries_synced,
    }
