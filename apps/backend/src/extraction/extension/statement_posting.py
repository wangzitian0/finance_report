"""Stage 1 statement posting guards and auto-approval helpers (DWD conform).

Posting guards now operate on the ``StatementSummary`` envelope and its Layer-2
``AtomicTransaction`` rows (resolved via the linked ODS ``UploadedDocument``),
instead of the legacy statement/transaction pair.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import STATEMENT_SOURCE_TYPES, JournalEntrySourceType, promote_entry_source_type
from src.audit.money.currency import normalize_currency_code
from src.extraction.extension.review_queue import create_entry_from_txn
from src.extraction.extension.statement_validation import approve_statement, resolve_statement_transactions
from src.extraction.extension.transaction_classification import classify_by_effective_policy
from src.extraction.orm.statement_enums import BankStatementStatus, Stage1Status
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType, JournalEntry, JournalEntryStatus

HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD = 85

# "Which of these atomic txns are already covered by an accepted transfer
# match" is reconciliation-owned knowledge. extraction must not import
# reconciliation (reconciliation already declares depends_on extraction — the
# reverse edge would be a dependency cycle), so the read arrives through a
# provider port: the app composition root (``src/main.py``, L4) registers
# reconciliation's published ``accepted_transfer_txn_ids`` at startup — the
# same inversion as ``workflow_events``' readiness provider (#1676, #1762).
# The edge was invisible while the match ORM lived in the unregistered
# ``src/models/`` remainder; the #1675 D5 move made it a governed import.
TransferExclusionsProvider = Callable[[AsyncSession, Sequence[UUID]], Awaitable[set[UUID]]]

_transfer_exclusions_provider: TransferExclusionsProvider | None = None


def register_transfer_exclusions_provider(provider: TransferExclusionsProvider) -> None:
    """Register the reconciliation-side transfer-exclusions read (composition root)."""
    global _transfer_exclusions_provider
    _transfer_exclusions_provider = provider


def _get_transfer_exclusions_provider() -> TransferExclusionsProvider:
    if _transfer_exclusions_provider is None:
        raise RuntimeError(
            "statement_posting.register_transfer_exclusions_provider() was never "
            "called — the app composition root (src/main.py) registers "
            "reconciliation's accepted_transfer_txn_ids at startup; tests that "
            "bypass app startup must register a provider explicitly."
        )
    return _transfer_exclusions_provider


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

    transfer_txn_ids = await _get_transfer_exclusions_provider()(db, txn_ids)

    txns_to_post = [
        txn for txn in transactions if txn.id not in existing_entry_txn_ids and txn.id not in transfer_txn_ids
    ]
    if not txns_to_post:
        return 0

    preloaded_bank_account = await resolve_statement_posting_account(db, statement, user_id)
    await validate_statement_period_unique(db, statement, user_id, preloaded_bank_account.id)

    # Classify BEFORE posting (#1545): ``create_entry_from_txn`` picks the
    # counter-account from an APPLIED classification, so a categorized txn posts to
    # its real category account instead of the Uncategorized bucket. The seam is
    # flag-gated FIRST (no policy evaluation when off => today's behaviour exactly)
    # and effective-dated per txn_date, so publishing a new basis version never
    # restates already-covered periods; uncovered dates are skipped, never fatal.
    await classify_by_effective_policy(db, user_id, txns_to_post)

    for txn in txns_to_post:
        # ``create_entry_from_txn`` consumes the Layer-2 ``AtomicTransaction``.
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
    currency = normalize_currency_code(statement.currency or "")
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

    currency = normalize_currency_code(statement.currency or "")
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
        select(StatementSummary).where(StatementSummary.id == statement_id).where(StatementSummary.user_id == user_id)
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
