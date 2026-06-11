import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logger import get_logger
from src.models.layer1 import DocumentType, UploadedDocument
from src.models.layer2 import AtomicPosition, AtomicTransaction, TransactionDirection
from src.models.statement_summary import StatementSummary

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
    statement: StatementSummary,
    transactions: list[AtomicTransaction],
    file_path: Path | None = None,
    original_filename: str | None = None,
    document_type: DocumentType | None = None,
    extraction_metadata: dict[str, Any] | None = None,
) -> None:
    """Persist the DWD ingestion result: ODS document, Layer-2 facts, conform summary.

    Single source of truth for an ingested statement. Given the parsed
    ``StatementSummary`` envelope and its ``AtomicTransaction`` rows (produced by
    ``ExtractionService.parse_document``), this:

    1. creates the Layer-1 ``UploadedDocument`` (ODS),
    2. upserts each ``AtomicTransaction`` (dedup by hash; the extracted running
       ``balance_after`` stashed on ``txn._extracted_balance_after`` is threaded back
       into the upsert hash so it matches the precomputed ``dedup_hash``),
    3. links ``StatementSummary.uploaded_document_id`` to the ODS document and
       persists the summary (DWD conform).

    Precondition: each transaction carries a precomputed ``dedup_hash`` and an
    optional transient ``_extracted_balance_after`` attribute.

    Raises RuntimeError on non-IntegrityError failures. IntegrityError (duplicate
    upload) is silently ignored.
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
    doc_type = document_type or doc_type_map.get((statement.institution or "").lower(), DocumentType.BANK_STATEMENT)
    file_hash = statement.file_hash

    try:
        uploaded_doc = await dedup_service.create_uploaded_document(
            db=db,
            user_id=user_id,
            file_path=str(file_path) if file_path else file_hash,
            file_hash=file_hash,
            original_filename=original_filename or file_hash,
            document_type=doc_type,
            extraction_metadata=extraction_metadata,
        )

        layer2_count = 0
        for txn in transactions:
            await dedup_service.upsert_atomic_transaction(
                db=db,
                user_id=user_id,
                txn_date=txn.txn_date,
                amount=txn.amount,
                direction=txn.direction,
                description=txn.description,
                currency=txn.currency or statement.currency or "SGD",
                source_doc_id=uploaded_doc.id,
                source_doc_type=doc_type,
                reference=txn.reference,
                balance_after=getattr(txn, "_extracted_balance_after", None),
            )
            layer2_count += 1

        # DWD conform: bind the confirmed envelope to its ODS document and persist.
        # The ingestion pipeline (statement upload) pre-creates the ``StatementSummary``
        # envelope in PARSING state keyed on ``(user_id, file_hash)``; reuse that row so
        # the confirmed parse result updates a single conform record (its id is the one
        # the API/router exposes) instead of colliding on the unique key.
        existing = (
            await db.execute(
                select(StatementSummary)
                .where(StatementSummary.user_id == user_id)
                .where(StatementSummary.file_hash == file_hash)
            )
        ).scalar_one_or_none()
        if existing is not None and existing is not statement:
            existing.account_id = statement.account_id if statement.account_id is not None else existing.account_id
            existing.institution = statement.institution
            existing.account_last4 = statement.account_last4
            existing.currency = statement.currency
            existing.period_start = statement.period_start
            existing.period_end = statement.period_end
            existing.opening_balance = statement.opening_balance
            existing.closing_balance = statement.closing_balance
            existing.extraction_metadata = statement.extraction_metadata
            existing.confidence_score = statement.confidence_score
            existing.balance_validated = statement.balance_validated
            existing.validation_error = statement.validation_error
            existing.status = statement.status
            existing.uploaded_document_id = uploaded_doc.id
            db.add(existing)
        else:
            statement.uploaded_document_id = uploaded_doc.id
            db.add(statement)
        await db.flush()

        logger.info(
            "Dual write to Layer 2 completed",
            uploaded_doc_id=str(uploaded_doc.id),
            statement_summary_id=str(statement.id),
            layer2_transactions=layer2_count,
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
            layer2_transactions=len(transactions),
        )
        # Re-raise to ensure caller knows dual-write failed
        raise RuntimeError(f"Failed to write to Layer 2: {e}") from e
