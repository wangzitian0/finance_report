"""Report package readiness derivation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models import (
    Account,
    AccountType,
    AtomicPosition,
    BankStatement,
    BankStatementStatus,
    BankStatementTransaction,
    CheckStatus,
    ConsistencyCheck,
    Direction,
    DividendIncome,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    ManualValuationSnapshot,
    MarketDataOverride,
    ReconciliationMatch,
    ReconciliationStatus,
    ReportSnapshot,
    Stage1Status,
)
from src.services.fx import FxRateError, convert_amount

PACKAGE_ID = "personal-financial-report-package"


def _blocker(
    code: str,
    label: str,
    count: int,
    reason: str,
    action_href: str,
    severity: str = "blocking",
) -> dict[str, str | int]:
    return {
        "code": code,
        "label": label,
        "severity": severity,
        "count": count,
        "reason": reason,
        "action_href": action_href,
    }


async def _count(db: AsyncSession, statement) -> int:
    return int(await db.scalar(statement) or 0)


async def _max_updated_at(db: AsyncSession, statement) -> datetime | None:
    return await db.scalar(statement)


async def _processing_account_balance(db: AsyncSession, user_id: UUID) -> Decimal:
    result = await db.execute(
        select(Account).where(
            Account.user_id == user_id,
            Account.is_system == True,  # noqa: E712
            Account.code == "1199",
        )
    )
    processing_account = result.scalar_one_or_none()
    if processing_account is None:
        return Decimal("0.00")

    result = await db.execute(
        select(JournalLine.direction, JournalLine.amount, JournalLine.currency, JournalEntry.entry_date)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id == processing_account.id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
    )
    target_currency = settings.base_currency.strip().upper()
    total = Decimal("0.00")
    for direction, amount, source_currency, entry_date in result.all():
        signed_amount = amount if direction == Direction.DEBIT else -amount
        total += await convert_amount(
            db,
            amount=signed_amount,
            currency=source_currency or processing_account.currency or target_currency,
            target_currency=target_currency,
            rate_date=entry_date,
            lazy_load=True,
        )
    return total


async def get_personal_report_package_readiness(db: AsyncSession, user_id: UUID) -> dict:
    """Return deterministic readiness for the personal financial-report package."""
    statement_count = await _count(
        db,
        select(func.count(BankStatement.id)).where(BankStatement.user_id == user_id),
    )
    active_account_count = await _count(
        db,
        select(func.count(Account.id)).where(
            Account.user_id == user_id,
            Account.is_active == True,  # noqa: E712
            Account.is_system == False,  # noqa: E712
        ),
    )
    journal_entry_count = await _count(
        db,
        select(func.count(JournalEntry.id)).where(
            JournalEntry.user_id == user_id,
            JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]),
        ),
    )
    position_count = await _count(
        db,
        select(func.count(AtomicPosition.id)).where(AtomicPosition.user_id == user_id),
    )
    manual_valuation_count = await _count(
        db,
        select(func.count(ManualValuationSnapshot.id)).where(ManualValuationSnapshot.user_id == user_id),
    )
    dividend_count = await _count(
        db,
        select(func.count(DividendIncome.id)).where(DividendIncome.user_id == user_id),
    )
    market_price_count = await _count(
        db,
        select(func.count(MarketDataOverride.id)).where(MarketDataOverride.user_id == user_id),
    )

    source_summary = {
        "statements": statement_count,
        "active_accounts": active_account_count,
        "posted_journal_entries": journal_entry_count,
        "positions": position_count,
        "manual_valuations": manual_valuation_count,
        "dividends": dividend_count,
        "market_prices": market_price_count,
    }
    report_input_count = (
        statement_count
        + journal_entry_count
        + position_count
        + manual_valuation_count
        + dividend_count
        + market_price_count
    )

    blockers: list[dict[str, str | int]] = []
    processing_count = await _count(
        db,
        select(func.count(BankStatement.id)).where(
            BankStatement.user_id == user_id,
            BankStatement.status.in_([BankStatementStatus.UPLOADED, BankStatementStatus.PARSING]),
        ),
    )

    failed_parsing_count = await _count(
        db,
        select(func.count(BankStatement.id)).where(
            BankStatement.user_id == user_id,
            BankStatement.status == BankStatementStatus.REJECTED,
        ),
    )
    if failed_parsing_count:
        blockers.append(
            _blocker(
                "failed_parsing",
                "Failed statement parsing",
                failed_parsing_count,
                "One or more uploaded statements failed parsing and cannot support a trusted package.",
                "/statements",
            )
        )

    pending_review_count = await _count(
        db,
        select(func.count(BankStatement.id)).where(
            BankStatement.user_id == user_id,
            BankStatement.stage1_status == Stage1Status.PENDING_REVIEW,
        ),
    )
    if pending_review_count:
        blockers.append(
            _blocker(
                "pending_review",
                "Pending source review",
                pending_review_count,
                "Statement review must be completed before the package can be marked ready.",
                "/review",
            )
        )

    balance_mismatch_count = await _count(
        db,
        select(func.count(BankStatement.id)).where(
            BankStatement.user_id == user_id,
            (BankStatement.balance_validated == False) | (BankStatement.validation_error.is_not(None)),  # noqa: E712
        ),
    )
    if balance_mismatch_count:
        blockers.append(
            _blocker(
                "balance_mismatch",
                "Balance validation mismatch",
                balance_mismatch_count,
                "Opening and closing balances must validate before report totals are trusted.",
                "/review",
            )
        )

    reconciliation_blocker_count = await _count(
        db,
        select(func.count(ReconciliationMatch.id))
        .join(BankStatementTransaction, ReconciliationMatch.bank_txn_id == BankStatementTransaction.id)
        .join(BankStatement, BankStatementTransaction.statement_id == BankStatement.id)
        .where(BankStatement.user_id == user_id)
        .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW),
    )
    if reconciliation_blocker_count:
        blockers.append(
            _blocker(
                "reconciliation_blocked",
                "Reconciliation blockers",
                reconciliation_blocker_count,
                "Pending reconciliation matches must be accepted or rejected before report readiness.",
                "/reconciliation/review-queue",
            )
        )

    consistency_blocker_count = await _count(
        db,
        select(func.count(ConsistencyCheck.id)).where(
            ConsistencyCheck.user_id == user_id,
            ConsistencyCheck.status == CheckStatus.PENDING,
        ),
    )
    if consistency_blocker_count:
        blockers.append(
            _blocker(
                "consistency_check_blocked",
                "Consistency checks pending",
                consistency_blocker_count,
                "Duplicate, transfer-pair, or anomaly checks must be resolved before package output is trusted.",
                "/review",
            )
        )

    try:
        processing_balance = (await _processing_account_balance(db, user_id)).quantize(Decimal("0.01"))
    except FxRateError as exc:
        blockers.append(
            _blocker(
                "processing_account_unresolved",
                "Processing account unresolved",
                1,
                f"Processing account balance cannot be converted to {settings.base_currency.strip().upper()}: {exc}",
                "/accounts/processing",
            )
        )
    else:
        if processing_balance != Decimal("0.00"):
            blockers.append(
                _blocker(
                    "processing_account_unresolved",
                    "Processing account unresolved",
                    1,
                    f"Processing account balance is {processing_balance} {settings.base_currency.strip().upper()}; in-transit transfer legs must net to zero.",
                    "/accounts/processing",
                )
            )

    approved_statement_accounts = select(BankStatement.account_id).where(
        BankStatement.user_id == user_id,
        BankStatement.account_id.is_not(None),
        BankStatement.status == BankStatementStatus.APPROVED,
    )
    missing_coverage_count = await _count(
        db,
        select(func.count(Account.id)).where(
            Account.user_id == user_id,
            Account.is_active == True,  # noqa: E712
            Account.is_system == False,  # noqa: E712
            Account.type.in_([AccountType.ASSET, AccountType.LIABILITY]),
            ~Account.id.in_(approved_statement_accounts),
        ),
    )
    if report_input_count and missing_coverage_count:
        blockers.append(
            _blocker(
                "missing_source_coverage",
                "Missing source coverage",
                missing_coverage_count,
                "Active asset or liability accounts need approved statement coverage or explicit source anchoring.",
                "/accounts/coverage",
            )
        )

    latest_snapshot_count = await _count(
        db,
        select(func.count(ReportSnapshot.id)).where(
            ReportSnapshot.user_id == user_id,
            ReportSnapshot.is_latest == True,  # noqa: E712
        ),
    )
    latest_snapshot_updated_at = await _max_updated_at(
        db,
        select(func.max(ReportSnapshot.updated_at)).where(
            ReportSnapshot.user_id == user_id,
            ReportSnapshot.is_latest == True,  # noqa: E712
        ),
    )

    source_updated_at_candidates = [
        await _max_updated_at(db, select(func.max(BankStatement.updated_at)).where(BankStatement.user_id == user_id)),
        await _max_updated_at(db, select(func.max(JournalEntry.updated_at)).where(JournalEntry.user_id == user_id)),
        await _max_updated_at(db, select(func.max(AtomicPosition.updated_at)).where(AtomicPosition.user_id == user_id)),
        await _max_updated_at(
            db, select(func.max(ManualValuationSnapshot.updated_at)).where(ManualValuationSnapshot.user_id == user_id)
        ),
        await _max_updated_at(db, select(func.max(DividendIncome.updated_at)).where(DividendIncome.user_id == user_id)),
        await _max_updated_at(
            db, select(func.max(MarketDataOverride.updated_at)).where(MarketDataOverride.user_id == user_id)
        ),
    ]
    source_updated_at = max((value for value in source_updated_at_candidates if value is not None), default=None)

    if processing_count and not blockers:
        state = "processing"
        label = "Processing"
        action_href = "/statements"
    elif blockers:
        state = "blocked"
        label = "Blocked"
        action_href = str(blockers[0]["action_href"])
    elif (
        latest_snapshot_count
        and latest_snapshot_updated_at
        and source_updated_at
        and source_updated_at > latest_snapshot_updated_at
    ):
        state = "stale"
        label = "Stale"
        action_href = "/reports/package"
    elif latest_snapshot_count:
        state = "generated"
        label = "Generated"
        action_href = "/reports/package"
    elif report_input_count:
        state = "ready"
        label = "Ready"
        action_href = "/reports/package"
    else:
        state = "draft"
        label = "Draft"
        action_href = "/statements/upload"

    return {
        "package_id": PACKAGE_ID,
        "state": state,
        "label": label,
        "action_href": action_href,
        "blocking_count": sum(int(blocker["count"]) for blocker in blockers),
        "blockers": blockers,
        "source_summary": source_summary,
        "generated_at": latest_snapshot_updated_at,
        "stale_since": source_updated_at if state == "stale" else None,
    }
