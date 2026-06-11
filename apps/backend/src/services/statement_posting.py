"""Stage 1 statement posting guards and auto-approval helpers (DWD conform).

Posting guards now operate on the ``StatementSummary`` envelope and its Layer-2
``AtomicTransaction`` rows (resolved via the linked ODS ``UploadedDocument``),
instead of the legacy ``BankStatement`` / ``BankStatementTransaction`` pair.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    ReconciliationMatch,
    ReconciliationStatus,
)
from src.models.statement_enums import BankStatementStatus, Stage1Status
from src.models.statement_summary import StatementSummary
from src.services.review_queue import create_entry_from_txn
from src.services.source_type_priority import STATEMENT_SOURCE_TYPES, promote_entry_source_type
from src.services.statement_validation import approve_statement, resolve_statement_transactions

HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD = 85


def is_high_confidence_auto_approve_candidate(statement: StatementSummary) -> bool:
    """Return whether parsing confidence is high enough for automatic Stage 1 approval."""
    return (
        statement.status == BankStatementStatus.APPROVED
        and statement.balance_validated is True
        and statement.confidence_score is not None
        and statement.confidence_score >= HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD
    )


async def auto_create_posted_entries_for_statement(
    db: AsyncSession,
    statement: StatementSummary,
    user_id: UUID,
) -> int:
    """Create posted journal entries after Stage 1 approval, guarded by mapping and period safety."""
    transactions = await resolve_statement_transactions(db, statement)
    txn_ids = [txn.id for txn in transactions]
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
        .where(ReconciliationMatch.atomic_txn_id.in_(txn_ids))
        .where(
            ReconciliationMatch.status.in_([ReconciliationStatus.AUTO_ACCEPTED, ReconciliationStatus.ACCEPTED]),
            ReconciliationMatch.superseded_by_id.is_(None),
        )
    )
    transfer_txn_ids = {
        match.atomic_txn_id for match in transfer_match_result.scalars().all() if match.journal_entry_ids
    }

    txns_to_post = [
        txn for txn in transactions if txn.id not in existing_entry_txn_ids and txn.id not in transfer_txn_ids
    ]
    if not txns_to_post:
        return 0

    preloaded_bank_account = await resolve_statement_posting_account(db, statement, user_id)
    await validate_statement_period_unique(db, statement, user_id, preloaded_bank_account.id)

    for txn in txns_to_post:
        # TODO(EPIC-011 Stage 3): create_entry_from_txn still consumes the legacy
        # BankStatementTransaction; its migration onto AtomicTransaction is owned by
        # the review_queue migration phase.
        await create_entry_from_txn(
            db,
            txn,
            user_id=user_id,
            auto_post=True,
            source_type=JournalEntrySourceType.USER_CONFIRMED,
            preloaded_bank_account=preloaded_bank_account,
        )

    return len(txns_to_post)


async def resolve_statement_posting_account(
    db: AsyncSession,
    statement: StatementSummary,
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
        .join(StatementSummary, StatementSummary.account_id == Account.id)
        .where(Account.user_id == user_id)
        .where(Account.type == AccountType.ASSET)
        .where(Account.currency == currency)
        .where(Account.is_active.is_(True))
        .where(StatementSummary.user_id == user_id)
        .where(StatementSummary.id != statement.id)
        .where(StatementSummary.status == BankStatementStatus.APPROVED)
        .where(StatementSummary.account_id.is_not(None))
        .where(func.lower(StatementSummary.institution) == institution.lower())
        .where(StatementSummary.account_last4 == account_last4)
        .where(func.upper(StatementSummary.currency) == currency)
    )
    accounts_by_id = {account.id: account for account in account_result.scalars().all()}
    if len(accounts_by_id) == 1:
        account = next(iter(accounts_by_id.values()))
        statement.account_id = account.id
        await db.flush()
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
    statement: StatementSummary,
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
        select(StatementSummary)
        .where(StatementSummary.user_id == user_id)
        .where(StatementSummary.id != statement.id)
        .where(StatementSummary.account_id == account_id)
        .where(StatementSummary.status == BankStatementStatus.APPROVED)
        .where(func.upper(StatementSummary.currency) == currency)
        .where(StatementSummary.period_start.is_not(None))
        .where(StatementSummary.period_end.is_not(None))
        .where(StatementSummary.period_start <= statement.period_end)
        .where(StatementSummary.period_end >= statement.period_start)
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
        select(StatementSummary)
        .where(StatementSummary.id == statement_id)
        .where(StatementSummary.user_id == user_id)
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
        refreshed = await db.get(StatementSummary, statement_id)
        if refreshed is not None:
            refreshed.status = BankStatementStatus.PARSED
            refreshed.stage1_status = Stage1Status.PENDING_REVIEW
            refreshed.validation_error = str(exc)[:500]
            await db.flush()
        return 0
