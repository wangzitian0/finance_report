"""Stage 1 statement posting guards and auto-approval helpers."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import (
    Account,
    AccountType,
    BankStatement,
    BankStatementStatus,
    BankStatementTransaction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    ReconciliationMatch,
    ReconciliationStatus,
)
from src.models.statement import Stage1Status
from src.services.review_queue import create_entry_from_txn
from src.services.source_type_priority import STATEMENT_SOURCE_TYPES, promote_entry_source_type
from src.services.statement_summary import sync_statement_summary
from src.services.statement_validation import approve_statement

HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD = 85


def is_high_confidence_auto_approve_candidate(statement: BankStatement) -> bool:
    """Return whether parsing confidence is high enough for automatic Stage 1 approval."""
    return (
        statement.status == BankStatementStatus.APPROVED
        and statement.balance_validated is True
        and statement.confidence_score is not None
        and statement.confidence_score >= HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD
    )


async def auto_create_posted_entries_for_statement(
    db: AsyncSession,
    statement: BankStatement,
    user_id: UUID,
) -> int:
    """Create posted journal entries after Stage 1 approval, guarded by mapping and period safety."""
    txn_ids = [txn.id for txn in statement.transactions]
    if not txn_ids:
        return 0

    existing_entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id.in_(txn_ids))
        .where(JournalEntry.status != JournalEntryStatus.VOID)
    )
    existing_entries = list(existing_entry_result.scalars().all())
    for entry in existing_entries:
        promote_entry_source_type(entry, JournalEntrySourceType.USER_CONFIRMED)
    existing_entry_txn_ids = {entry.source_id for entry in existing_entries}

    transfer_match_result = await db.execute(
        select(ReconciliationMatch)
        .join(BankStatementTransaction, ReconciliationMatch.bank_txn_id == BankStatementTransaction.id)
        .join(BankStatement, BankStatementTransaction.statement_id == BankStatement.id)
        .where(ReconciliationMatch.bank_txn_id.in_(txn_ids))
        .where(
            ReconciliationMatch.status.in_([ReconciliationStatus.AUTO_ACCEPTED, ReconciliationStatus.ACCEPTED]),
            ReconciliationMatch.superseded_by_id.is_(None),
        )
        .where(BankStatement.user_id == user_id)
    )
    transfer_txn_ids = {match.bank_txn_id for match in transfer_match_result.scalars().all() if match.journal_entry_ids}

    txns_to_post = [
        txn for txn in statement.transactions if txn.id not in existing_entry_txn_ids and txn.id not in transfer_txn_ids
    ]
    if not txns_to_post:
        return 0

    preloaded_bank_account = await resolve_statement_posting_account(db, statement, user_id)
    await validate_statement_period_unique(db, statement, user_id, preloaded_bank_account.id)

    for txn in txns_to_post:
        await create_entry_from_txn(
            db,
            txn,
            user_id=user_id,
            auto_post=True,
            source_type=JournalEntrySourceType.USER_CONFIRMED,
            preloaded_statement=statement,
            preloaded_bank_account=preloaded_bank_account,
        )

    return len(txns_to_post)


async def resolve_statement_posting_account(
    db: AsyncSession,
    statement: BankStatement,
    user_id: UUID,
) -> Account:
    """Resolve the asset account for automatic posting without generic fallback."""
    currency = (statement.currency or "").strip().upper()
    if not currency:
        raise ValueError("Statement currency required before posting. Confirm the source currency before posting.")

    if statement.account_id:
        account_result = await db.execute(
            select(Account).where(Account.id == statement.account_id).where(Account.user_id == user_id)
        )
        account = account_result.scalar_one_or_none()
        if account is None:
            raise ValueError("Statement account mapping is invalid. Confirm the target account before posting.")
        if account.type != AccountType.ASSET or not account.is_active:
            raise ValueError(
                "Statement account mapping must reference an active asset account. "
                "Confirm the target account before posting."
            )
        if account.currency != currency:
            raise ValueError(
                "Statement account mapping must match the statement currency. "
                "Confirm the target account before posting."
            )
        return account

    institution = (statement.institution or "").strip()
    account_last4 = (statement.account_last4 or "").strip()
    if not institution or not account_last4 or not currency:
        raise ValueError(
            "Account mapping required before posting. Confirm the statement account because institution, "
            "account_last4, or currency metadata is missing."
        )

    account_result = await db.execute(
        select(Account)
        .join(BankStatement, BankStatement.account_id == Account.id)
        .where(Account.user_id == user_id)
        .where(Account.type == AccountType.ASSET)
        .where(Account.currency == currency)
        .where(Account.is_active.is_(True))
        .where(BankStatement.user_id == user_id)
        .where(BankStatement.id != statement.id)
        .where(BankStatement.status == BankStatementStatus.APPROVED)
        .where(BankStatement.account_id.is_not(None))
        .where(func.lower(BankStatement.institution) == institution.lower())
        .where(BankStatement.account_last4 == account_last4)
        .where(func.upper(BankStatement.currency) == currency)
    )
    accounts_by_id = {account.id: account for account in account_result.scalars().all()}
    if len(accounts_by_id) == 1:
        account = next(iter(accounts_by_id.values()))
        statement.account_id = account.id
        await db.flush()
        await sync_statement_summary(db, statement)
        return account
    if len(accounts_by_id) > 1:
        raise ValueError(
            "Ambiguous account mapping. Multiple accounts match this statement's institution, account_last4, "
            "and currency; confirm the target account before posting."
        )
    raise ValueError(
        "Account mapping required before posting. No confirmed account matches this statement's institution, "
        "account_last4, and currency."
    )


async def validate_statement_period_unique(
    db: AsyncSession,
    statement: BankStatement,
    user_id: UUID,
    account_id: UUID,
) -> None:
    """Block posted entries when the statement source period is missing, duplicated, or overlapping."""
    if statement.period_start is None or statement.period_end is None:
        raise ValueError("Statement period required before posting. Confirm the source date range before posting.")
    if statement.period_start > statement.period_end:
        raise ValueError("Statement period is invalid. Confirm the source date range before posting.")

    currency = (statement.currency or "").strip().upper()
    if not currency:
        raise ValueError("Statement currency required before posting. Confirm the source currency before posting.")

    overlap_result = await db.execute(
        select(BankStatement)
        .where(BankStatement.user_id == user_id)
        .where(BankStatement.id != statement.id)
        .where(BankStatement.account_id == account_id)
        .where(BankStatement.status == BankStatementStatus.APPROVED)
        .where(func.upper(BankStatement.currency) == currency)
        .where(BankStatement.period_start.is_not(None))
        .where(BankStatement.period_end.is_not(None))
        .where(BankStatement.period_start <= statement.period_end)
        .where(BankStatement.period_end >= statement.period_start)
        .limit(1)
    )
    overlapping_statement = overlap_result.scalar_one_or_none()
    if overlapping_statement:
        raise ValueError(
            "Statement period overlaps an approved statement for this account and currency. "
            "Resolve the duplicate source date range before posting."
        )


async def try_auto_approve_high_confidence_statement(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
) -> int:
    """Auto-approve and post a high-confidence parsed statement when all posting guards pass.

    If a high-confidence statement cannot be safely posted automatically, leave it in
    Stage 1 pending review instead of failing parsing.
    """
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .where(BankStatement.user_id == user_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one_or_none()
    if statement is None or not is_high_confidence_auto_approve_candidate(statement):
        return 0

    try:
        async with db.begin_nested():
            approved = await approve_statement(db, statement_id, user_id)
            created_count = await auto_create_posted_entries_for_statement(db, approved, user_id)
            await db.flush()
        return created_count
    except ValueError as exc:
        refreshed = await db.get(BankStatement, statement_id)
        if refreshed is not None:
            refreshed.status = BankStatementStatus.PARSED
            refreshed.stage1_status = Stage1Status.PENDING_REVIEW
            refreshed.validation_error = str(exc)[:500]
            await db.flush()
        return 0
