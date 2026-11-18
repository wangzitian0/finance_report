"""Read-model projections and ownership lookups for the reconciliation router."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from src.extraction import (
    AtomicTransaction,
    BankStatementStatus,
    StatementSummary,
    effective_statement_transaction_filter,
)
from src.ledger import Account, JournalEntry
from src.observability import get_logger
from src.platform import ResourceNotFoundError, get_owned_or_raise, paginate
from src.reconciliation.data.stats import posted_statement_source_ids
from src.reconciliation.extension.entry_reads import entry_total_amount
from src.reconciliation.orm.reconciliation import ReconciliationMatch, ReconciliationStatus

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReconciledEntrySummary:
    """Lightweight read projection of a journal entry attached to a reconciliation match."""

    id: UUID
    entry_date: date
    memo: str | None
    status: str
    total_amount: Decimal


def build_entry_summary(entry: JournalEntry) -> ReconciledEntrySummary:
    """Project a loaded ``JournalEntry`` (with lines) into ``ReconciledEntrySummary``."""
    lines = getattr(entry, "lines", None)
    return ReconciledEntrySummary(
        id=entry.id,
        entry_date=entry.entry_date,
        memo=entry.memo,
        status=entry.status.value,
        total_amount=entry_total_amount(entry, currency=lines[0].currency if lines else "SGD"),
    )


def unmatched_atomic_txn_query(user_id: UUID, *, include_pending_stage1: bool = False):
    """Build the SQL query for unmatched, unposted effective atomic transactions of a user."""
    matched_txn = aliased(AtomicTransaction)
    matched_subquery = (
        select(ReconciliationMatch.atomic_txn_id)
        .join(matched_txn, matched_txn.id == ReconciliationMatch.atomic_txn_id)
        .where(
            matched_txn.user_id == user_id,
            ReconciliationMatch.status.notin_((ReconciliationStatus.REJECTED, ReconciliationStatus.SUPERSEDED)),
            ReconciliationMatch.superseded_by_id.is_(None),
            ReconciliationMatch.atomic_txn_id.is_not(None),
        )
    )
    return select(AtomicTransaction).where(
        effective_statement_transaction_filter(user_id, include_pending_stage1=include_pending_stage1),
        AtomicTransaction.id.notin_(matched_subquery),
        AtomicTransaction.id.notin_(posted_statement_source_ids(user_id)),
    )


def statement_atomic_txn_ids_query(statement: StatementSummary) -> Select[tuple[UUID]]:
    """Build the SQL query selecting effective atomic transaction IDs for a statement."""
    return select(AtomicTransaction.id).where(effective_statement_transaction_filter(statement.user_id, statement.id))


async def load_entry_summaries_for_matches(
    db: AsyncSession, matches: Sequence[ReconciliationMatch], user_id: UUID
) -> dict[str, ReconciledEntrySummary]:
    """Batch-load journal entry summaries referenced by ``matches`` for ``user_id``."""
    if not matches:
        return {}
    entry_ids: set[UUID] = set()
    for match in matches:
        for eid in match.journal_entry_ids or []:
            try:
                entry_ids.add(UUID(eid))
            except ValueError:
                logger.warning("Invalid UUID in journal_entry_ids", match_id=str(match.id), invalid_entry_id=eid)
    if not entry_ids:
        return {}
    return {
        str(e.id): build_entry_summary(e)
        for e in (
            await db.execute(
                select(JournalEntry)
                .where(JournalEntry.id.in_(entry_ids), JournalEntry.user_id == user_id)
                .options(selectinload(JournalEntry.lines))
            )
        )
        .scalars()
        .all()
    }


async def load_transactions_for_matches(
    db: AsyncSession, matches: Sequence[ReconciliationMatch], user_id: UUID | None = None
) -> dict[UUID, AtomicTransaction]:
    """Batch-load ``AtomicTransaction`` rows referenced by ``matches``."""
    if not matches:
        return {}
    txn_ids = {m.atomic_txn_id for m in matches}
    return await load_transactions_by_ids(db, txn_ids, user_id=user_id)


async def load_transactions_by_ids(
    db: AsyncSession, txn_ids: set[UUID], *, user_id: UUID | None = None
) -> dict[UUID, AtomicTransaction]:
    """Batch-load ``AtomicTransaction`` rows keyed by ID, optionally scoped to ``user_id``."""
    if not txn_ids:
        return {}
    stmt = select(AtomicTransaction).where(AtomicTransaction.id.in_(txn_ids))
    if user_id is not None:
        stmt = stmt.where(AtomicTransaction.user_id == user_id)
    return {t.id: t for t in (await db.execute(stmt)).scalars().all()}


async def load_journal_entry_summary_by_id(db: AsyncSession, entry_id: UUID) -> ReconciledEntrySummary:
    """Reload one journal entry with its lines and project to ``ReconciledEntrySummary``."""
    entry_with_lines = (
        await db.execute(
            select(JournalEntry).options(selectinload(JournalEntry.lines)).where(JournalEntry.id == entry_id)
        )
    ).scalar_one()
    return build_entry_summary(entry_with_lines)


async def get_active_reconciliation_statement(db: AsyncSession, statement_id: UUID, user_id: UUID) -> StatementSummary:
    """Return an owned non-retired statement, or raise ``ResourceNotFoundError``."""
    statement = await get_owned_or_raise(db, StatementSummary, statement_id, user_id, name="Statement")
    if statement.status is BankStatementStatus.RETIRED:
        raise ResourceNotFoundError("Statement not found")
    return statement


async def get_owned_reconciliation_transaction(db: AsyncSession, txn_id: UUID, user_id: UUID) -> AtomicTransaction:
    """Return an owned ``AtomicTransaction`` or raise ``ResourceNotFoundError``."""
    return await get_owned_or_raise(db, AtomicTransaction, txn_id, user_id, name="Transaction")


async def get_owned_adjustment_account(db: AsyncSession, account_id: UUID, user_id: UUID) -> Account:
    """Return an owned ``Account`` or raise ``ResourceNotFoundError``."""
    return await get_owned_or_raise(db, Account, account_id, user_id, name="Account")


async def count_unmatched_transactions(
    db: AsyncSession,
    *,
    user_id: UUID,
    statement: StatementSummary | None = None,
) -> int:
    """Count unmatched effective transactions for a user, optionally scoped to one statement."""
    unmatched_query = unmatched_atomic_txn_query(user_id, include_pending_stage1=statement is not None)
    if statement is not None:
        unmatched_query = unmatched_query.where(AtomicTransaction.id.in_(statement_atomic_txn_ids_query(statement)))
    return int((await db.execute(select(func.count()).select_from(unmatched_query.subquery()))).scalar_one())


async def list_reconciliation_matches_page(
    db: AsyncSession,
    *,
    user_id: UUID,
    status: ReconciliationStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[ReconciliationMatch], int]:
    """Return one paginated slice of user-owned reconciliation matches."""
    clauses = [AtomicTransaction.user_id == user_id]
    if status is not None:
        clauses.append(ReconciliationMatch.status == status)
    query = (
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(*clauses)
    )
    return await paginate(db, query, limit=limit, offset=offset, order_by=(ReconciliationMatch.created_at.desc(),))


async def list_unmatched_transactions_page(
    db: AsyncSession,
    *,
    user_id: UUID,
    statement_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[Sequence[AtomicTransaction], int]:
    """Return one paginated slice of unmatched effective atomic transactions."""
    query = unmatched_atomic_txn_query(user_id, include_pending_stage1=statement_id is not None)
    if statement_id is not None:
        statement = await get_owned_or_raise(db, StatementSummary, statement_id, user_id, name="Statement")
        query = query.where(AtomicTransaction.id.in_(statement_atomic_txn_ids_query(statement)))
    return await paginate(db, query, limit=limit, offset=offset, order_by=(AtomicTransaction.txn_date.desc(),))
