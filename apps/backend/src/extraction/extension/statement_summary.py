"""DWD custody-account resolution (EPIC-011 PR-B).

``resolve_custody_account_id`` is the DWD-native lookup the reconciliation
transfer-detection path uses: given a Layer-2 ``AtomicTransaction``, resolve its
custody account from the ``StatementSummary`` conform via the source document.

The ``StatementSummary`` conform is now written directly by the ingestion pipeline
(``ExtractionService.parse_document`` + ``dual_write_layer2``), so the legacy
``BankStatement`` -> ``StatementSummary`` mirror (``sync_statement_summary``) is gone.

Also holds the three registered-port implementations for ``StatementSummary``'s
remaining cross-domain readers (#1675 D6): ``get_statement_event_sources``
(consumed directly by the ``workflow`` domain package),
``get_statement_coverage_rows`` (``ledger``, same-rank cycle — read via
``register_statement_coverage_reader``), and ``find_in_flight_parse_id``
(``identity``, same-rank cycle — read via
``register_in_flight_parse_checker``). Each returns a plain read-model shape
owned by the *reader*, never the ``StatementSummary`` ORM instance itself —
main.py wires all three at startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer1 import DocumentType, UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_enums import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import StatementCoverageRow

if TYPE_CHECKING:
    from collections.abc import Collection


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


async def get_statement_coverage_rows(
    db: AsyncSession, user_id: UUID, account_ids: Collection[UUID]
) -> list[StatementCoverageRow]:
    """Read model for ledger's account-coverage port (#1675 D6).

    Returns every APPROVED ``StatementSummary`` row for the given accounts as
    the plain ``StatementCoverageRow`` shape ``ledger`` accepts through its
    registered ``register_statement_coverage_reader`` port — the status
    filter stays here since ``BankStatementStatus`` is this package's enum.
    """
    result = await db.execute(
        select(StatementSummary)
        .where(StatementSummary.user_id == user_id)
        .where(StatementSummary.status == BankStatementStatus.APPROVED)
        .where(StatementSummary.account_id.in_(account_ids))
        .order_by(
            StatementSummary.account_id,
            StatementSummary.currency,
            StatementSummary.period_start,
            StatementSummary.id,
        )
    )
    return [
        StatementCoverageRow(
            id=statement.id,
            # Filtered to account_ids above, so account_id is never NULL here.
            account_id=statement.account_id,  # type: ignore[arg-type]
            currency=statement.currency,
            period_start=statement.period_start,
            period_end=statement.period_end,
            opening_balance=statement.opening_balance,
            closing_balance=statement.closing_balance,
            updated_at=statement.updated_at,
        )
        for statement in result.scalars().all()
    ]


async def find_in_flight_parse_id(db: AsyncSession, user_id: UUID) -> UUID | None:
    """Read model for identity's delete-guard port (#1675 D6).

    Returns the id of a ``StatementSummary`` currently ``PARSING`` for this
    user, or ``None``. identity's delete-user endpoint uses this (through its
    registered ``register_in_flight_parse_checker`` port) to refuse a delete
    that would race a still-running background parse (#1256, AC13.23.1).
    """
    return await db.scalar(
        select(StatementSummary.id)
        .where(StatementSummary.user_id == user_id)
        .where(StatementSummary.status == BankStatementStatus.PARSING)
        .limit(1)
    )
