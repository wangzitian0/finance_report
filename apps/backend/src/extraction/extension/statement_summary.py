"""DWD custody-account resolution (EPIC-011 PR-B).

``resolve_custody_account_id`` is the DWD-native lookup the reconciliation
transfer-detection path uses: given a Layer-2 ``AtomicTransaction``, resolve its
custody account from the ``StatementSummary`` conform via the source document.

The ``StatementSummary`` conform is now written directly by the ingestion pipeline
(``ExtractionService.parse_document`` + ``dual_write_layer2``), so the legacy
``BankStatement`` -> ``StatementSummary`` mirror (``sync_statement_summary``) is gone.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer1 import DocumentType, UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction
from src.models.statement_summary import StatementSummary


def _ordered_bank_statement_doc_ids(source_documents: object) -> list[UUID]:
    """Extract source ``UploadedDocument`` ids, in order, for bank-statement sources.

    Accepts the canonical list form (``[{"doc_id": ..., "doc_type": ...}]``) and a
    ``{"documents": [...]}`` wrapper. Non-bank-statement sources are ignored (custody
    is a cash/bank-account concept), entries with a missing ``doc_type`` are kept,
    and invalid UUID strings are skipped so they never raise during query binding.
    """
    if isinstance(source_documents, dict):
        source_documents = source_documents.get("documents", [])
    if not isinstance(source_documents, list):
        return []

    bank_statement = DocumentType.BANK_STATEMENT.value
    ordered: list[UUID] = []
    seen: set[UUID] = set()
    for entry in source_documents:
        if not isinstance(entry, dict):
            continue
        doc_type = entry.get("doc_type")
        if doc_type is not None and doc_type != bank_statement:
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


async def resolve_custody_account_id(db: AsyncSession, atomic_txn: AtomicTransaction) -> UUID | None:
    """Resolve the custody account for a Layer-2 atomic transaction via the conform.

    Walks ``atomic_txn.source_documents -> UploadedDocument -> StatementSummary`` and
    returns the confirmed custody ``account_id`` of the **first** source document (in
    source-document order) that has one. Returns ``None`` when no source statement has
    a confirmed custody account.
    """
    doc_ids = _ordered_bank_statement_doc_ids(atomic_txn.source_documents)
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
