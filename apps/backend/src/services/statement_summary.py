"""StatementSummary conform sync + custody-account resolution (EPIC-011 PR-A).

``sync_statement_summary`` mirrors a ``BankStatement`` envelope into the durable
``StatementSummary`` conform table (keyed by ``(user_id, file_hash)``), linking
the ODS ``UploadedDocument`` when present. It is called at statement
finalization points (parse completion, confirm/approve/reject/edit) so the
conform stays current while the legacy ``bank_statements`` table is still the
write path.

``resolve_custody_account_id`` is the DWD-native lookup the reconciliation
transfer-detection path will use (PR-B): given a Layer-2 ``AtomicTransaction``,
resolve its custody account from the conform via the source document, instead of
reaching back into the legacy ``bank_statements.account_id`` (ODS).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logger import get_logger
from src.models.layer1 import UploadedDocument
from src.models.layer2 import AtomicTransaction
from src.models.statement import BankStatement
from src.models.statement_summary import StatementSummary

logger = get_logger(__name__)

# Envelope fields copied verbatim from BankStatement -> StatementSummary.
_ENVELOPE_FIELDS = (
    "account_id",
    "institution",
    "account_last4",
    "currency",
    "period_start",
    "period_end",
    "opening_balance",
    "closing_balance",
    "manual_opening_balance",
    "status",
    "stage1_status",
    "confidence_score",
    "balance_validated",
    "validation_error",
    "balance_validation_result",
    "stage1_reviewed_at",
    "extraction_metadata",
)


async def sync_statement_summary(db: AsyncSession, statement: BankStatement) -> StatementSummary:
    """Upsert the StatementSummary conform from a BankStatement's current envelope.

    Idempotent: keyed by ``(user_id, file_hash)``; re-running refreshes the
    envelope in place. Does not commit (caller owns the transaction).
    """
    summary = (
        await db.execute(
            select(StatementSummary).where(
                StatementSummary.user_id == statement.user_id,
                StatementSummary.file_hash == statement.file_hash,
            )
        )
    ).scalar_one_or_none()

    uploaded_document_id = (
        await db.execute(
            select(UploadedDocument.id).where(
                UploadedDocument.user_id == statement.user_id,
                UploadedDocument.file_hash == statement.file_hash,
            )
        )
    ).scalar_one_or_none()

    values = {field: getattr(statement, field) for field in _ENVELOPE_FIELDS}

    if summary is None:
        summary = StatementSummary(
            user_id=statement.user_id,
            file_hash=statement.file_hash,
            uploaded_document_id=uploaded_document_id,
            **values,
        )
        db.add(summary)
    else:
        if uploaded_document_id is not None:
            summary.uploaded_document_id = uploaded_document_id
        for field, value in values.items():
            setattr(summary, field, value)

    await db.flush()
    return summary


async def resolve_custody_account_id(db: AsyncSession, atomic_txn: AtomicTransaction) -> UUID | None:
    """Resolve the custody account for a Layer-2 atomic transaction via the conform.

    Walks ``atomic_txn.source_documents -> UploadedDocument -> StatementSummary``
    and returns the first confirmed custody ``account_id``. Returns ``None`` when
    the source statement has no linked account yet.
    """
    source_docs = atomic_txn.source_documents if isinstance(atomic_txn.source_documents, list) else []
    doc_ids = [d["doc_id"] for d in source_docs if isinstance(d, dict) and d.get("doc_id")]
    if not doc_ids:
        return None

    file_hashes = (
        (
            await db.execute(
                select(UploadedDocument.file_hash).where(
                    UploadedDocument.user_id == atomic_txn.user_id,
                    UploadedDocument.id.in_(doc_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    if not file_hashes:
        return None

    return (
        await db.execute(
            select(StatementSummary.account_id)
            .where(
                StatementSummary.user_id == atomic_txn.user_id,
                StatementSummary.file_hash.in_(file_hashes),
                StatementSummary.account_id.isnot(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
