import hashlib
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logger import get_logger
from src.models.layer1 import DocumentType, UploadedDocument
from src.models.layer2 import AtomicPosition, AtomicTransaction, TransactionDirection

logger = get_logger(__name__)


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
    ) -> str:
        """Calculate deduplication hash for atomic transaction.

        Hash = SHA256(user_id|date|amount|direction|description|reference)
        """
        components = [
            str(user_id),
            txn_date.isoformat(),
            str(amount),
            direction.value,
            description.strip().lower(),
            reference or "",
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
    ) -> AtomicTransaction:
        """Upsert atomic transaction with deduplication.

        If dedup_hash exists -> Append to source_documents array
        If dedup_hash new -> Insert new record
        """
        dedup_hash = self.calculate_transaction_hash(
            user_id, txn_date, amount, direction, description, reference
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
