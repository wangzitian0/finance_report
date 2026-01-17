"""Review queue management for reconciliation."""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
) -> ReconciliationMatch:
    """Accept a pending reconciliation match."""
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

    match.status = ReconciliationStatus.ACCEPTED
    match.version += 1
    txn = match.transaction
    if txn:
        txn.status = BankStatementTransactionStatus.MATCHED

    if match.journal_entry_ids:
        entry_ids = [UUID(entry_id) for entry_id in match.journal_entry_ids]
        result = await db.execute(
            select(JournalEntry)
            .where(JournalEntry.id.in_(entry_ids))
            .where(JournalEntry.user_id == user_id)
        )
        for entry in result.scalars():
            if entry.status != JournalEntryStatus.VOID:
                entry.status = JournalEntryStatus.RECONCILED

    await db.commit()
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

    await db.commit()
    return match


logger = logging.getLogger(__name__)


async def batch_accept(
    db: AsyncSession,
    match_ids: list[str],
    *,
    user_id: UUID,
    min_score: int = 80,
) -> list[ReconciliationMatch]:
    """Batch accept high-score matches.

    Note: Per EPIC-004 Q4 design, only matches with score >= min_score are accepted.
    Lower-scoring matches are intentionally skipped to require individual review.
    Skipped matches are logged for transparency.
    """
    if not match_ids:
        return []
    result = await db.execute(
        select(ReconciliationMatch)
        .join(BankStatementTransaction)
        .join(BankStatement)
        .where(ReconciliationMatch.id.in_(match_ids))
        .where(BankStatement.user_id == user_id)
        .where(ReconciliationMatch.match_score >= min_score)
        .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW)
        .with_for_update()
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
        match.status = ReconciliationStatus.ACCEPTED
        match.version += 1
        accepted.append(match)
        result_txn = await db.execute(
            select(BankStatementTransaction).where(BankStatementTransaction.id == match.bank_txn_id)
        )
        txn = result_txn.scalar_one_or_none()
        if txn:
            txn.status = BankStatementTransactionStatus.MATCHED

        if match.journal_entry_ids:
            entry_ids = [UUID(entry_id) for entry_id in match.journal_entry_ids]
            result_entries = await db.execute(
                select(JournalEntry)
                .where(JournalEntry.id.in_(entry_ids))
                .where(JournalEntry.user_id == user_id)
            )
            for entry in result_entries.scalars():
                if entry.status != JournalEntryStatus.VOID:
                    entry.status = JournalEntryStatus.RECONCILED

    await db.commit()
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
    await db.commit()
    await db.refresh(account)
    return account


async def create_entry_from_txn(
    db: AsyncSession,
    txn: BankStatementTransaction,
    *,
    user_id: UUID,
) -> JournalEntry:
    """Create a draft journal entry from a bank transaction."""
    # Validate transaction belongs to user
    stmt_check = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == txn.statement_id)
        .where(BankStatement.user_id == user_id)
    )
    if not stmt_check.scalar_one_or_none():
        raise ValueError("Transaction does not belong to user")

    currency = "SGD"
    if txn.statement_id:
        statement_result = await db.execute(
            select(BankStatement).where(BankStatement.id == txn.statement_id)
        )
        statement = statement_result.scalar_one_or_none()
        if statement and statement.currency:
            currency = statement.currency

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
    await db.commit()
    await db.refresh(entry, ["lines"])
    return entry
