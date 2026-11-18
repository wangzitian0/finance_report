"""DWD custody-account resolution (EPIC-011 PR-B).

``resolve_custody_account_id`` is the DWD-native lookup the reconciliation
transfer-detection path uses: given a Layer-2 ``AtomicTransaction``, resolve its
custody account from the ``StatementSummary`` conform via the source document.

The ``StatementSummary`` conform is now written directly by the ingestion pipeline
(``ExtractionService.parse_document`` + ``dual_write_layer2``), so the legacy
``BankStatement`` -> ``StatementSummary`` mirror (``sync_statement_summary``) is gone.

Also holds ``get_statement_event_sources`` (consumed directly by the
``workflow`` domain package), returning a plain read-model shape owned by
extraction rather than leaking the ``StatementSummary`` ORM instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.base.source_vocabulary import DocumentType
from src.extraction.base.types import extract_source_document_ids
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary


@dataclass(frozen=True)
class StatementEventSource:
    """Extraction-owned statement read shape consumed by workflow derivation."""

    id: UUID
    user_id: UUID
    uploaded_document_id: UUID | None
    file_hash: str
    status: str
    stage1_status: str | None
    created_at: datetime
    updated_at: datetime | None
    stage1_reviewed_at: datetime | None


async def resolve_custody_account_id(db: AsyncSession, atomic_txn: AtomicTransaction) -> UUID | None:
    """Resolve the custody account for a Layer-2 atomic transaction via the conform.

    Walks ``atomic_txn.source_documents -> UploadedDocument -> StatementSummary`` and
    returns the confirmed custody ``account_id`` of the **first** source document (in
    source-document order) that has one. Returns ``None`` when no source statement has
    a confirmed custody account.
    """
    doc_ids = extract_source_document_ids(atomic_txn.source_documents, doc_type=DocumentType.BANK_STATEMENT.value)
    if not doc_ids:
        return None

    # doc_id -> file_hash for the source documents.
    doc_hash_rows = (
        await db.execute(
            select(UploadedDocument.id, UploadedDocument.file_hash).where(
                UploadedDocument.user_id == atomic_txn.user_id,
                UploadedDocument.id.in_(doc_ids),
            )
        )
    ).all()
    hash_by_doc_id = {doc_id: file_hash for doc_id, file_hash in doc_hash_rows}
    if not hash_by_doc_id:
        return None

    # file_hash -> confirmed custody account.
    account_rows = (
        await db.execute(
            select(StatementSummary.file_hash, StatementSummary.account_id).where(
                StatementSummary.user_id == atomic_txn.user_id,
                StatementSummary.file_hash.in_(hash_by_doc_id.values()),
                StatementSummary.account_id.isnot(None),
            )
        )
    ).all()
    account_by_hash = {file_hash: account_id for file_hash, account_id in account_rows}

    # Preserve source-document order: first source with a confirmed account wins.
    for doc_id in doc_ids:
        account_id = account_by_hash.get(hash_by_doc_id.get(doc_id))
        if account_id is not None:
            return account_id
    return None


async def get_statement_event_sources(db: AsyncSession, user_id: UUID) -> list[StatementEventSource]:
    """Read model for workflow event derivation.

    Returns every ``StatementSummary`` row for the user as the plain
    ``StatementEventSource`` shape instead of leaking the ORM class or enum
    types. Ordered by creation so workflow does not need a second sort.
    """
    result = await db.execute(
        select(StatementSummary).where(StatementSummary.user_id == user_id).order_by(StatementSummary.created_at)
    )
    return [
        StatementEventSource(
            id=statement.id,
            user_id=statement.user_id,
            uploaded_document_id=statement.uploaded_document_id,
            file_hash=statement.file_hash,
            status=statement.status.value,
            stage1_status=statement.stage1_status.value if statement.stage1_status is not None else None,
            created_at=statement.created_at,
            updated_at=statement.updated_at,
            stage1_reviewed_at=statement.stage1_reviewed_at,
        )
        for statement in result.scalars().all()
    ]
