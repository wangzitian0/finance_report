"""Review queue management for reconciliation."""

from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import settings
from src.logger import get_logger
from src.models import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
    ReconciliationMatch,
    ReconciliationStatus,
)
from src.models.layer1 import DocumentType, UploadedDocument
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.layer3 import ClassificationStatus, TransactionClassification
from src.models.statement_summary import StatementSummary
from src.services.accounting import ValidationError, validate_journal_balance, validate_journal_posting_invariants
from src.services.currency_resolution import CurrencyUnresolvedError
from src.services.fx import FxRateError, get_exchange_rate
from src.services.reconciliation import entry_total_amount, sync_reconciliation_match_journal_entry_links
from src.services.source_type_priority import (
    STATEMENT_SOURCE_TYPES,
    normalize_source_type,
    promote_entry_source_type,
)

logger = get_logger(__name__)


def _source_document_ids(source_documents: object) -> list[UUID]:
    """Extract source ``UploadedDocument`` ids (bank-statement sources), in order.

    Mirrors ``statement_summary._ordered_bank_statement_doc_ids``: accepts the
    canonical list form (``[{"doc_id": ..., "doc_type": ...}]``) and a
    ``{"documents": [...]}`` wrapper, keeps entries with a missing ``doc_type``,
    and skips invalid UUID strings so they never raise during query binding.
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


async def _resolve_statement_summary(
    db: AsyncSession,
    txn: AtomicTransaction,
    *,
    user_id: UUID,
) -> StatementSummary | None:
    """Resolve the owning ``StatementSummary`` for an atomic transaction.

    Walks ``txn.source_documents -> UploadedDocument -> StatementSummary`` and
    returns the first source document's statement summary (in source-document
    order). Returns ``None`` when no source document maps to a statement summary.
    """
    doc_ids = _source_document_ids(txn.source_documents)
    if not doc_ids:
        return None

    result = await db.execute(
        select(StatementSummary)
        .join(UploadedDocument, StatementSummary.uploaded_document_id == UploadedDocument.id)
        .where(StatementSummary.user_id == user_id)
        .where(UploadedDocument.id.in_(doc_ids))
    )
    summaries = {summary.uploaded_document_id: summary for summary in result.scalars()}
    for doc_id in doc_ids:
        summary = summaries.get(doc_id)
        if summary is not None:
            return summary
    return None


async def get_pending_items(
    db: AsyncSession,
    *,
    user_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[ReconciliationMatch]:
    """Return pending review reconciliation matches."""
    result = await db.execute(
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(AtomicTransaction.user_id == user_id)
        .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
        .order_by(ReconciliationMatch.match_score.desc())
        .limit(limit)
        .offset(offset)
        .options(selectinload(ReconciliationMatch.atomic_transaction))
    )
    return cast(list[ReconciliationMatch], result.scalars().all())


async def accept_match(
    db: AsyncSession,
    match_id: str,
    *,
    user_id: UUID,
    skip_amount_validation: bool = False,
) -> ReconciliationMatch:
    """Accept a pending reconciliation match.

    Args:
        db: Database session
        match_id: ID of the match to accept
        user_id: User ID for authorization
        skip_amount_validation: If True, skip amount sum validation (for edge cases)

    Raises:
        ValueError: If match not found or amount validation fails
    """
    result = await db.execute(
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(ReconciliationMatch.id == match_id)
        .where(AtomicTransaction.user_id == user_id)
        .options(selectinload(ReconciliationMatch.atomic_transaction))
        .with_for_update()
    )
    match = result.scalar_one_or_none()
    if not match:
        raise ValueError("Match not found")

    if match.status != ReconciliationStatus.PENDING_REVIEW:
        return match

    txn = match.atomic_transaction

    if txn and not match.journal_entry_ids:
        existing_entry_result = await db.execute(
            select(JournalEntry)
            .where(JournalEntry.user_id == user_id)
            .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
            .where(JournalEntry.source_id == txn.id)
            .where(JournalEntry.status != JournalEntryStatus.VOID)
            .limit(1)
            .with_for_update()
        )
        existing_entry = existing_entry_result.scalar_one_or_none()
        if existing_entry:
            match.journal_entry_ids = [str(existing_entry.id)]
        else:
            created_entry = await create_entry_from_txn(db, txn, user_id=user_id, auto_post=True)
            match.journal_entry_ids = [str(created_entry.id)]

    # Validate that journal entry amounts match transaction amount
    if match.journal_entry_ids and txn and not skip_amount_validation:
        entry_ids = [UUID(entry_id) for entry_id in match.journal_entry_ids]
        entries_result = await db.execute(
            select(JournalEntry)
            .where(JournalEntry.id.in_(entry_ids))
            .where(JournalEntry.user_id == user_id)
            .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
        )
        entries = list(entries_result.scalars())

        # Use entry_total_amount() to correctly sum all debit lines
        total_entry_amount = sum(entry_total_amount(entry) for entry in entries)

        # Allow 1% tolerance or $0.10, whichever is greater
        tolerance = max(txn.amount * Decimal("0.01"), Decimal("0.10"))
        if abs(total_entry_amount - txn.amount) > tolerance:
            raise ValueError(
                f"Amount mismatch: transaction={txn.amount}, entries={total_entry_amount}, tolerance={tolerance}"
            )

    match.status = ReconciliationStatus.ACCEPTED
    match.version += 1

    if match.journal_entry_ids:
        entry_ids = [UUID(entry_id) for entry_id in match.journal_entry_ids]
        result = await db.execute(
            select(JournalEntry).where(JournalEntry.id.in_(entry_ids)).where(JournalEntry.user_id == user_id)
        )
        for entry in result.scalars():
            if entry.status != JournalEntryStatus.VOID:
                entry.status = JournalEntryStatus.RECONCILED
                promote_entry_source_type(entry, JournalEntrySourceType.USER_CONFIRMED)

    await db.flush()
    await sync_reconciliation_match_journal_entry_links(db, match)
    return match


async def reject_match(
    db: AsyncSession,
    match_id: str,
    *,
    user_id: UUID,
) -> ReconciliationMatch:
    """Reject a pending reconciliation match."""
    result = await db.execute(
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(ReconciliationMatch.id == match_id)
        .where(AtomicTransaction.user_id == user_id)
        .options(selectinload(ReconciliationMatch.atomic_transaction))
        .with_for_update()
    )
    match = result.scalar_one_or_none()
    if not match:
        raise ValueError("Match not found")

    if match.status != ReconciliationStatus.PENDING_REVIEW:
        return match

    match.status = ReconciliationStatus.REJECTED
    match.version += 1

    await db.flush()
    return match


async def batch_accept(
    db: AsyncSession,
    match_ids: list[str],
    *,
    user_id: UUID,
    min_score: int = 80,
) -> list[ReconciliationMatch]:
    """Batch accept high-score matches."""
    if not match_ids:
        return []

    # Optimization: join atomic transaction and load it to avoid N+1 queries later
    result = await db.execute(
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(ReconciliationMatch.id.in_(match_ids))
        .where(AtomicTransaction.user_id == user_id)
        .where(ReconciliationMatch.match_score >= min_score)
        .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
        .options(selectinload(ReconciliationMatch.atomic_transaction))
        .with_for_update(of=ReconciliationMatch)
    )
    matches = result.scalars().all()
    matched_ids = {str(m.id) for m in matches}
    skipped_ids = set(match_ids) - matched_ids
    if skipped_ids:
        logger.info(
            "batch_accept: %d of %d matches skipped (score < %d or not pending): %s",
            len(skipped_ids),
            len(match_ids),
            min_score,
            list(skipped_ids),
        )

    accepted: list[ReconciliationMatch] = []
    for match in matches:
        accepted.append(await accept_match(db, str(match.id), user_id=user_id))

    await db.flush()
    return accepted


async def get_or_create_account(
    db: AsyncSession,
    *,
    name: str,
    account_type: AccountType,
    currency: str,
    user_id: UUID,
) -> Account:
    """Fetch or create a default account."""
    result = await db.execute(
        select(Account)
        .where(Account.name == name)
        .where(Account.type == account_type)
        .where(Account.currency == currency)
        .where(Account.user_id == user_id)
    )
    account = result.scalar_one_or_none()
    if account:
        return account

    account = Account(
        user_id=user_id,
        name=name,
        type=account_type,
        currency=currency,
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


async def create_entry_from_txn(
    db: AsyncSession,
    txn: AtomicTransaction,
    *,
    user_id: UUID,
    auto_post: bool = False,
    source_type: JournalEntrySourceType = JournalEntrySourceType.AUTO_PARSED,
    preloaded_statement: StatementSummary | None = None,
    preloaded_bank_account: Account | None = None,
) -> JournalEntry:
    """Create a journal entry from an atomic transaction.

    Uses the owning statement summary's linked account if available. Draft entries
    may still use the legacy default account, but posted entries require an explicit
    mapping. When auto_post is True, the generated entry is first persisted as
    DRAFT with its lines and then promoted to POSTED; otherwise it remains DRAFT.
    preloaded_statement/preloaded_bank_account may be passed by trusted callers
    that already loaded them for the same authenticated user context.

    The owning statement is resolved via ``txn.source_documents -> UploadedDocument
    -> StatementSummary`` (atomic transactions have no ``statement_id``).
    """
    # Validate transaction belongs to user and resolve owning statement summary.
    if txn.user_id != user_id:
        raise ValueError("Transaction does not belong to user")

    # Promotion-gate (EPIC-012 AC12.40.4): a transaction whose currency could not be
    # established at the ingest boundary is non-authoritative. It cannot become a
    # JournalLine until a reviewer specifies the currency (see resolve_transaction_currency).
    # This is the load-bearing guard that makes JournalLine.currency human-confirmed.
    if getattr(txn, "currency_unresolved", False):
        raise CurrencyUnresolvedError(
            f"Transaction {txn.id} has an unresolved currency and cannot be promoted to a "
            "journal entry. A reviewer must specify its currency first."
        )

    statement = preloaded_statement
    if statement is not None:
        # Caller must preload statement under the same authenticated user context.
        if statement.user_id != user_id:
            raise ValueError("Preloaded statement does not match transaction or user")
    else:
        statement = await _resolve_statement_summary(db, txn, user_id=user_id)

    currency = ((statement.currency if statement else None) or txn.currency or "SGD").upper()
    base_currency = settings.base_currency.upper()
    line_fx_rate: Decimal | None = None
    if currency != base_currency:
        try:
            line_fx_rate = await get_exchange_rate(db, currency, base_currency, txn.txn_date)
        except FxRateError as exc:
            raise ValueError(f"FX rate required to create {currency} journal entry: {exc}") from exc

    # Use statement's linked account if available.
    statement_account_id = statement.account_id if statement else None
    bank_account: Account | None = preloaded_bank_account
    if bank_account is not None:
        if bank_account.user_id != user_id:
            # Caller must preload bank account under the same authenticated user context.
            raise ValueError("Bank account does not belong to user")
        if statement_account_id and bank_account.id != statement_account_id:
            raise ValueError("Preloaded bank account does not match statement")
    elif statement_account_id:
        account_result = await db.execute(
            select(Account).where(Account.id == statement_account_id).where(Account.user_id == user_id)
        )
        bank_account = account_result.scalar_one_or_none()

    if not bank_account and auto_post:
        raise ValueError("Account mapping required before posting. Confirm the statement account before posting.")

    if not bank_account:
        # Fallback: create or get default bank account
        bank_account = await get_or_create_account(
            db,
            name="Bank - Main",
            account_type=AccountType.ASSET,
            currency=currency,
            user_id=user_id,
        )

    classified_account: Account | None = None
    classification_result = await db.execute(
        select(TransactionClassification)
        .where(TransactionClassification.atomic_txn_id == txn.id)
        .where(TransactionClassification.status == ClassificationStatus.APPLIED)
        .order_by(TransactionClassification.created_at.desc())
    )
    classification = classification_result.scalar_one_or_none()
    if classification and classification.account_id:
        account_result = await db.execute(select(Account).where(Account.id == classification.account_id))
        classified_account = account_result.scalar_one_or_none()

    if txn.direction == TransactionDirection.IN:
        if classified_account and classified_account.type == AccountType.INCOME:
            counter_account = classified_account
        else:
            counter_account = await get_or_create_account(
                db,
                name="Income - Uncategorized",
                account_type=AccountType.INCOME,
                currency=currency,
                user_id=user_id,
            )
        debit_account = bank_account
        credit_account = counter_account
    else:
        if classified_account and classified_account.type == AccountType.EXPENSE:
            counter_account = classified_account
        else:
            counter_account = await get_or_create_account(
                db,
                name="Expense - Uncategorized",
                account_type=AccountType.EXPENSE,
                currency=currency,
                user_id=user_id,
            )
        debit_account = counter_account
        credit_account = bank_account

    entry = JournalEntry(
        user_id=user_id,
        entry_date=txn.txn_date,
        memo=txn.description,
        source_type=normalize_source_type(source_type),
        source_id=txn.id,
        status=JournalEntryStatus.DRAFT,
    )

    entry.lines.append(
        JournalLine(
            account=debit_account,
            direction=Direction.DEBIT,
            amount=txn.amount,
            currency=currency,
            fx_rate=line_fx_rate,
            event_type="bank_txn",
        )
    )
    entry.lines.append(
        JournalLine(
            account=credit_account,
            direction=Direction.CREDIT,
            amount=txn.amount,
            currency=currency,
            fx_rate=line_fx_rate,
            event_type="bank_txn",
        )
    )

    try:
        if auto_post:
            validate_journal_posting_invariants(entry)
        else:
            validate_journal_balance(entry.lines)
    except ValidationError as exc:
        if not auto_post:
            raise ValueError(f"Generated entry does not balance: {exc}") from exc
        raise ValueError(f"Generated entry violates accounting invariants: {exc}") from exc

    db.add(entry)
    await db.flush()
    if auto_post:
        entry.status = JournalEntryStatus.POSTED
        await db.flush()
    await db.refresh(entry, ["lines"])

    # Eager evidence-graph lineage (AtomicTransaction --posted_as--> JournalEntry
    # --contains--> JournalLine). Imported lazily to avoid an import cycle.
    # Best-effort: provenance must never break journal posting.
    try:
        from src.services.evidence_graph_integration import EvidenceGraphIntegrationService

        await EvidenceGraphIntegrationService().record_journal_posting(
            db,
            user_id=user_id,
            atomic_transaction=txn,
            journal_entry=entry,
        )
    except Exception as evidence_exc:
        logger.warning(
            "Evidence-graph journal-posting lineage failed (posting continues)",
            extra={
                "error": str(evidence_exc),
                "error_type": type(evidence_exc).__name__,
                "user_id": str(user_id),
                "journal_entry_id": str(entry.id),
            },
        )

    return entry


async def get_stage2_queue(
    db: AsyncSession,
    user_id: UUID,
    run_id: str | None = None,
) -> list[ReconciliationMatch]:
    """Return matches pending Stage 2 review for a user."""
    query = (
        select(ReconciliationMatch)
        .join(AtomicTransaction, ReconciliationMatch.atomic_txn_id == AtomicTransaction.id)
        .where(
            ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW,
            AtomicTransaction.user_id == user_id,
        )
        .options(selectinload(ReconciliationMatch.atomic_transaction))
        .limit(50)
    )
    if run_id:
        query = query.where(ReconciliationMatch.run_id == run_id)

    result = await db.execute(query)
    return list(result.scalars().all())
