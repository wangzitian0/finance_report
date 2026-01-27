"""Review queue management for reconciliation."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.logger import get_logger
from src.models import (
    Account,
    AccountType,
    BankStatement,
    BankStatementTransaction,
    BankStatementTransactionStatus,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
    ReconciliationMatch,
    ReconciliationStatus,
)
from src.services.accounting import ValidationError, validate_journal_balance
from src.services.reconciliation import entry_total_amount


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
        .join(BankStatementTransaction)
        .join(BankStatement)
        .where(BankStatement.user_id == user_id)
        .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
        .order_by(ReconciliationMatch.match_score.desc())
        .limit(limit)
        .offset(offset)
        .options(selectinload(ReconciliationMatch.transaction))
    )
    return result.scalars().all()


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
        .join(BankStatementTransaction)
        .join(BankStatement)
        .where(ReconciliationMatch.id == match_id)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(ReconciliationMatch.transaction))
        .with_for_update()
    )
    match = result.scalar_one_or_none()
    if not match:
        raise ValueError("Match not found")

    if match.status != ReconciliationStatus.PENDING_REVIEW:
        return match

    txn = match.transaction

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
    if txn:
        txn.status = BankStatementTransactionStatus.MATCHED

    if match.journal_entry_ids:
        entry_ids = [UUID(entry_id) for entry_id in match.journal_entry_ids]
        result = await db.execute(
            select(JournalEntry).where(JournalEntry.id.in_(entry_ids)).where(JournalEntry.user_id == user_id)
        )
        for entry in result.scalars():
            if entry.status != JournalEntryStatus.VOID:
                entry.status = JournalEntryStatus.RECONCILED

    await db.flush()
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
        .join(BankStatementTransaction)
        .join(BankStatement)
        .where(ReconciliationMatch.id == match_id)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(ReconciliationMatch.transaction))
        .with_for_update()
    )
    match = result.scalar_one_or_none()
    if not match:
        raise ValueError("Match not found")

    if match.status != ReconciliationStatus.PENDING_REVIEW:
        return match

    match.status = ReconciliationStatus.REJECTED
    match.version += 1
    txn = match.transaction
    if txn:
        txn.status = BankStatementTransactionStatus.UNMATCHED

    await db.flush()
    return match


logger = get_logger(__name__)


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

    # Optimization: join transaction and load it to avoid N+1 queries later
    result = await db.execute(
        select(ReconciliationMatch)
        .join(BankStatementTransaction)
        .join(BankStatement)
        .where(ReconciliationMatch.id.in_(match_ids))
        .where(BankStatement.user_id == user_id)
        .where(ReconciliationMatch.match_score >= min_score)
        .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
        .options(selectinload(ReconciliationMatch.transaction))
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
    # Collect all entry IDs to pre-fetch them
    all_entry_ids = []
    for match in matches:
        if match.journal_entry_ids:
            all_entry_ids.extend([UUID(eid) for eid in match.journal_entry_ids])

    # Pre-fetch all journal entries to avoid N+1 queries in the loop
    entries_map = {}
    if all_entry_ids:
        entries_result = await db.execute(
            select(JournalEntry).where(JournalEntry.id.in_(all_entry_ids)).where(JournalEntry.user_id == user_id)
        )
        entries_map = {entry.id: entry for entry in entries_result.scalars().all()}

    for match in matches:
        match.status = ReconciliationStatus.ACCEPTED
        match.version += 1
        accepted.append(match)

        # Already loaded via selectinload
        txn = match.transaction
        if txn:
            txn.status = BankStatementTransactionStatus.MATCHED

        if match.journal_entry_ids:
            for entry_id_str in match.journal_entry_ids:
                entry = entries_map.get(UUID(entry_id_str))
                if entry and entry.status != JournalEntryStatus.VOID:
                    entry.status = JournalEntryStatus.RECONCILED

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
    txn: BankStatementTransaction,
    *,
    user_id: UUID,
) -> JournalEntry:
    """Create a draft journal entry from a bank transaction.

    Uses the statement's linked account if available, otherwise creates a default.
    """
    # Validate transaction belongs to user and get statement details
    statement_result = await db.execute(
        select(BankStatement).where(BankStatement.id == txn.statement_id).where(BankStatement.user_id == user_id)
    )
    statement = statement_result.scalar_one_or_none()
    if not statement:
        raise ValueError("Transaction does not belong to user")

    currency = statement.currency or "SGD"

    # Use statement's linked account if available, otherwise create default
    bank_account: Account | None = None
    if statement.account_id:
        account_result = await db.execute(
            select(Account).where(Account.id == statement.account_id).where(Account.user_id == user_id)
        )
        bank_account = account_result.scalar_one_or_none()

    if not bank_account:
        # Fallback: create or get default bank account
        bank_account = await get_or_create_account(
            db,
            name="Bank - Main",
            account_type=AccountType.ASSET,
            currency=currency,
            user_id=user_id,
        )
    if txn.direction == "IN":
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
        source_type=JournalEntrySourceType.BANK_STATEMENT,
        source_id=txn.id,
        status=JournalEntryStatus.DRAFT,
    )

    entry.lines.append(
        JournalLine(
            account_id=debit_account.id,
            direction=Direction.DEBIT,
            amount=txn.amount,
            currency=currency,
            event_type="bank_txn",
        )
    )
    entry.lines.append(
        JournalLine(
            account_id=credit_account.id,
            direction=Direction.CREDIT,
            amount=txn.amount,
            currency=currency,
            event_type="bank_txn",
        )
    )

    try:
        validate_journal_balance(entry.lines)
    except ValidationError as exc:
        raise ValueError(f"Generated entry does not balance: {exc}") from exc

    txn.status = BankStatementTransactionStatus.PENDING
    db.add(entry)
    await db.flush()
    await db.refresh(entry, ["lines"])
    return entry
