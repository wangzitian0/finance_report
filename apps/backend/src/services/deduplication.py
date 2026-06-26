import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logger import get_logger
from src.models.layer1 import DocumentStatus, DocumentType, UploadedDocument
from src.models.layer2 import (
    AtomicPosition,
    AtomicPositionSourceDocument,
    AtomicTransaction,
    AtomicTransactionSourceDocument,
    TransactionDirection,
)
from src.models.statement_summary import StatementSummary
from src.services.currency_resolution import resolve_ingest_currency

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
        occurrence_index: int = 0,
    ) -> str:
        """Calculate deduplication hash for atomic transaction.

        Hash = SHA256(user_id|date|amount|direction|description|reference|disambiguator)

        The disambiguator pairs the statement running balance (when present) with a
        per-document ``occurrence_index`` so auto-dedup collapses only when we are
        confident two rows are the SAME transaction, while preserving recall for
        genuinely-distinct rows:

        - ``balance_after`` present: the running balance normally pins the ledger
          position, but it is **not** a unique key on its own. A statement can print the
          *same* running balance against two genuinely-distinct same-date/same-amount
          rows — e.g. a deposit immediately before a carried-forward balance row and an
          identical deposit immediately after the brought-forward balance row across a
          page boundary (#1254). The ``occurrence_index`` keeps those two real rows
          distinct instead of silently dropping the second, while a re-uploaded statement
          reproduces the same ordered rows (same balance + same ordinal per row) so the
          genuine duplicate still collapses across documents.
        - No running balance (e.g. CSV): the ``occurrence_index`` alone keeps
          genuinely-repeated identical rows distinct (two $5 coffees on the same day are
          two transactions). Cross-document duplicates of such rows are left to the
          ``detect_duplicates`` consistency check for user review rather than dropped here.

        Backward compatibility: the **first** occurrence (``occurrence_index == 0``) keeps
        the legacy disambiguator byte-for-byte — ``"<balance>"`` when a balance is present
        and ``"#0"`` when it is not — so every hash persisted under the previous scheme
        still matches and cross-document dedup of already-stored rows is unaffected. Only
        *subsequent* occurrences of an otherwise-identical row gain the ``"#<index>"``
        tail (``"<balance>#1"``, ``"<balance>#2"`` …), which by definition never collided
        with a stored hash before (the second row was being dropped). This delivers the
        #1254 fix without changing any existing row's hash.

        Decimal amounts are canonicalized (``Decimal('50')`` and ``Decimal('50.00')``
        hash identically) so values that differ only in scale do not break dedup.
        """
        balance_key = _decimal_key(balance_after) if balance_after is not None else ""
        # occurrence_index == 0 -> legacy disambiguator (balance_key, or "#0" when balance-less),
        # so previously-stored hashes are preserved. Only index >= 1 gains the distinguishing tail.
        if occurrence_index == 0:
            disambiguator = balance_key if balance_after is not None else "#0"
        else:
            disambiguator = f"{balance_key}#{occurrence_index}"
        components = [
            str(user_id),
            txn_date.isoformat(),
            _decimal_key(amount),
            direction.value,
            description.strip().lower(),
            reference or "",
            disambiguator,
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
        occurrence_index: int = 0,
        currency_unresolved: bool = False,
    ) -> AtomicTransaction:
        """Upsert atomic transaction with deduplication.

        If dedup_hash exists -> Append to source_documents array
        If dedup_hash new -> Insert new record

        ``currency_unresolved`` (EPIC-012 AC12.40.2) flags a new row whose currency
        could not be determined at the ingest boundary; ``currency`` then holds a
        non-authoritative placeholder and the row is blocked from promotion until a
        reviewer specifies the currency.
        """
        dedup_hash = self.calculate_transaction_hash(
            user_id, txn_date, amount, direction, description, reference, balance_after, occurrence_index
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
            # Opportunistically backfill balance_after for legacy rows persisted before the
            # column existed. The dedup hash already matched, so the disambiguator (and thus the
            # running balance fed into it) is identical -- this only fills a NULL, never rewrites a
            # value. Without this, pre-migration rows stay NULL forever and the Stage-1 guard keeps
            # treating them as ambiguous, so already-stuck statements would not benefit from the fix.
            if existing.balance_after is None and balance_after is not None:
                existing.balance_after = balance_after

            source_docs = existing.source_documents
            if not isinstance(source_docs, list):
                source_docs = []

            if source_doc not in source_docs:
                source_docs.append(source_doc)
                existing.source_documents = source_docs
                await db.flush()
            await self._upsert_transaction_source_link(
                db,
                user_id=user_id,
                atomic_txn_id=existing.id,
                source_doc_id=source_doc_id,
                source_doc_type=source_doc_type,
                ordinal=source_docs.index(source_doc) if source_doc in source_docs else 0,
            )

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
            currency_unresolved=currency_unresolved,
            balance_after=balance_after,
            dedup_hash=dedup_hash,
            source_documents=[source_doc],
        )
        db.add(new_txn)
        await db.flush()
        await self._upsert_transaction_source_link(
            db,
            user_id=user_id,
            atomic_txn_id=new_txn.id,
            source_doc_id=source_doc_id,
            source_doc_type=source_doc_type,
            ordinal=0,
        )

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
            await self._upsert_position_source_link(
                db,
                user_id=user_id,
                atomic_position_id=existing.id,
                source_doc_id=source_doc_id,
                source_doc_type=source_doc_type,
                ordinal=source_docs.index(source_doc) if source_doc in source_docs else 0,
            )

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
        await self._upsert_position_source_link(
            db,
            user_id=user_id,
            atomic_position_id=new_pos.id,
            source_doc_id=source_doc_id,
            source_doc_type=source_doc_type,
            ordinal=0,
        )

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

    async def _upsert_transaction_source_link(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        atomic_txn_id: UUID,
        source_doc_id: UUID,
        source_doc_type: DocumentType,
        ordinal: int,
    ) -> None:
        document = await db.get(UploadedDocument, source_doc_id)
        if document is None or document.user_id != user_id:
            return

        existing = await db.get(AtomicTransactionSourceDocument, (atomic_txn_id, source_doc_id))
        if existing is None:
            db.add(
                AtomicTransactionSourceDocument(
                    atomic_txn_id=atomic_txn_id,
                    uploaded_document_id=source_doc_id,
                    doc_type=source_doc_type.value,
                    ordinal=ordinal,
                )
            )
        else:
            existing.doc_type = source_doc_type.value
            existing.ordinal = ordinal
        await db.flush()

    async def _upsert_position_source_link(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        atomic_position_id: UUID,
        source_doc_id: UUID,
        source_doc_type: DocumentType,
        ordinal: int,
    ) -> None:
        document = await db.get(UploadedDocument, source_doc_id)
        if document is None or document.user_id != user_id:
            return

        existing = await db.get(AtomicPositionSourceDocument, (atomic_position_id, source_doc_id))
        if existing is None:
            db.add(
                AtomicPositionSourceDocument(
                    atomic_position_id=atomic_position_id,
                    uploaded_document_id=source_doc_id,
                    doc_type=source_doc_type.value,
                    ordinal=ordinal,
                )
            )
        else:
            existing.doc_type = source_doc_type.value
            existing.ordinal = ordinal
        await db.flush()

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


async def _detach_document_from_atomic_transactions(db: Any, user_id: UUID, doc_id: UUID) -> None:
    """Remove a document's contribution to Layer 2 before a reparse re-ingests it.

    Atomic transactions sourced *solely* from this document are deleted (the reparse
    will recreate the current set); transactions also sourced from other documents
    keep the row but drop this document from ``source_documents``.
    """
    doc_id_str = str(doc_id)
    rows = (
        (
            await db.execute(
                select(AtomicTransaction)
                .where(AtomicTransaction.user_id == user_id)
                .where(AtomicTransaction.source_documents.contains([{"doc_id": doc_id_str}]))
            )
        )
        .scalars()
        .all()
    )
    for txn in rows:
        sources = txn.source_documents if isinstance(txn.source_documents, list) else []
        remaining = [s for s in sources if s.get("doc_id") != doc_id_str]
        if remaining:
            txn.source_documents = remaining
            db.add(txn)
        else:
            await db.delete(txn)
        await db.execute(
            AtomicTransactionSourceDocument.__table__.delete().where(
                AtomicTransactionSourceDocument.atomic_txn_id == txn.id,
                AtomicTransactionSourceDocument.uploaded_document_id == doc_id,
            )
        )
    if rows:
        await db.flush()


async def dual_write_layer2(
    db: Any,
    user_id: UUID,
    statement: StatementSummary,
    transactions: list[AtomicTransaction],
    file_path: Path | None = None,
    original_filename: str | None = None,
    document_type: DocumentType | None = None,
    extraction_metadata: dict[str, Any] | None = None,
    envelope_only: bool = False,
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
        # Get-or-create the ODS document. Reparse re-runs ingestion for the same
        # (user_id, file_hash), so the document already exists; reuse it instead of
        # raising on the unique key (which previously aborted the whole dual-write and
        # made reparse a silent no-op). On reparse, drop this document's prior parse
        # output first so the fresh extraction replaces it rather than accumulating.
        existing_doc = (
            await db.execute(
                select(UploadedDocument)
                .where(UploadedDocument.user_id == user_id)
                .where(UploadedDocument.file_hash == file_hash)
            )
        ).scalar_one_or_none()
        if existing_doc is not None:
            uploaded_doc = existing_doc
            uploaded_doc.original_filename = original_filename or uploaded_doc.original_filename
            if extraction_metadata is not None:
                uploaded_doc.extraction_metadata = extraction_metadata
            # ``envelope_only`` persists just the terminal envelope status (a
            # quarantined/rejected re-parse, #1452): it must NOT detach the
            # document's previously-ingested Layer-2 facts, or a re-parse that
            # ends in quarantine would delete a prior good parse's transactions.
            if not envelope_only:
                await _detach_document_from_atomic_transactions(db, user_id, uploaded_doc.id)
        else:
            uploaded_doc = await dedup_service.create_uploaded_document(
                db=db,
                user_id=user_id,
                file_path=str(file_path) if file_path else file_hash,
                file_hash=file_hash,
                original_filename=original_filename or file_hash,
                document_type=doc_type,
                extraction_metadata=extraction_metadata,
            )

        # Lazily import to avoid an import cycle (evidence_graph_integration imports
        # models that transitively reach back here).
        from src.services.evidence_graph_integration import EvidenceGraphIntegrationService

        evidence_graph = EvidenceGraphIntegrationService()

        layer2_count = 0
        for txn in transactions:
            # EPIC-012 AC12.40.1/.2: the currency is decided once at the ingest boundary
            # in ``ExtractionService.parse_document`` via ``resolve_ingest_currency`` and
            # stashed on ``txn._currency_unresolved`` (alongside the resolved/placeholder
            # code already on ``txn.currency``). Callers that build transactions outside
            # that path fall back to a fresh resolution over the model + statement fields
            # so this stays the single DB-write boundary and never silent-defaults.
            if hasattr(txn, "_currency_unresolved"):
                resolved_code = txn.currency
                currency_unresolved = bool(txn._currency_unresolved)
            else:
                resolved = resolve_ingest_currency(txn.currency, statement.currency)
                resolved_code = resolved.code
                currency_unresolved = resolved.unresolved
            upserted_txn = await dedup_service.upsert_atomic_transaction(
                db=db,
                user_id=user_id,
                txn_date=txn.txn_date,
                amount=txn.amount,
                direction=txn.direction,
                description=txn.description,
                currency=resolved_code,
                currency_unresolved=currency_unresolved,
                source_doc_id=uploaded_doc.id,
                source_doc_type=doc_type,
                reference=txn.reference,
                balance_after=getattr(txn, "_extracted_balance_after", None),
                occurrence_index=getattr(txn, "_occurrence_index", 0),
            )
            layer2_count += 1

            # Eager evidence-graph lineage (UploadedDocument --deduped_into-->
            # AtomicTransaction). Best-effort: provenance must never break the
            # money/atomic write, which is the priority.
            try:
                await evidence_graph.record_layer2_dual_write(
                    db,
                    user_id=user_id,
                    uploaded_document=uploaded_doc,
                    atomic_transaction=upserted_txn,
                    document_type=doc_type,
                )
            except Exception as evidence_exc:
                logger.warning(
                    "Evidence-graph dual-write lineage failed (ingestion continues)",
                    error=str(evidence_exc),
                    error_type=type(evidence_exc).__name__,
                    user_id=str(user_id),
                    atomic_transaction_id=str(upserted_txn.id),
                )

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
            # parse_document builds a fresh StatementSummary and sets stage1_status there, but this
            # reused envelope is the row that gets persisted. Mirror the freshly-computed
            # pending-review marker onto it, without clobbering a state that was already reviewed
            # (approved/rejected) on a re-parse.
            if existing.stage1_status is None:
                existing.stage1_status = statement.stage1_status
            existing.uploaded_document_id = uploaded_doc.id
            db.add(existing)
        else:
            statement.uploaded_document_id = uploaded_doc.id
            db.add(statement)
        # Reaching here means the parse succeeded and its facts are persisted, so the ODS document
        # advances out of 'uploaded'. Without this the status never progresses and every document
        # appears perpetually un-processed.
        uploaded_doc.status = DocumentStatus.COMPLETED
        db.add(uploaded_doc)
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
