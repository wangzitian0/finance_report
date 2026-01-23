"""Reporting service for financial statements and analytics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.constants.error_ids import ErrorIds
from src.logger import get_logger
from src.models import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)
from src.services.fx import FxRateError, PrefetchedFxRates, convert_amount

logger = get_logger(__name__)

_REPORT_STATUSES = (JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED)


class ReportError(Exception):
    """Raised when report generation fails or input is invalid."""

    pass


@dataclass
class PeriodSpan:
    start: date
    end: date


def _normalize_currency(code: str | None) -> str:
    if not code:
        return settings.base_currency.upper()
    return code.strip().upper()


def _signed_amount(account_type: AccountType, direction: Direction, amount: Decimal) -> Decimal:
    if account_type in (AccountType.ASSET, AccountType.EXPENSE):
        return amount if direction == Direction.DEBIT else -amount
    return amount if direction == Direction.CREDIT else -amount


def _quantize_money(amount: Decimal | int) -> Decimal:
    if isinstance(amount, int):
        amount = Decimal(amount)
    return amount.quantize(Decimal("0.01"))


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _month_end(value: date) -> date:
    next_month = value.replace(day=28) + timedelta(days=4)
    return next_month.replace(day=1) - timedelta(days=1)


def _quarter_start(value: date) -> date:
    month = ((value.month - 1) // 3) * 3 + 1
    return date(year=value.year, month=month, day=1)


def _add_months(value: date, months: int) -> date:
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    day = min(value.day, _month_end(date(year, month, 1)).day)
    return date(year, month, day)


# Limit to ~1 year of daily data to ensure report performance and prevent memory issues.
MAX_TREND_POINTS = 366


def _iter_periods(start: date, end: date, period: str) -> list[PeriodSpan]:
    spans: list[PeriodSpan] = []
    cursor = start

    while cursor <= end:
        if period == "daily":
            span_start = cursor
            span_end = cursor
            next_cursor = cursor + timedelta(days=1)
        elif period == "weekly":
            span_start = cursor - timedelta(days=cursor.weekday())
            span_end = span_start + timedelta(days=6)
            next_cursor = span_start + timedelta(days=7)
        elif period == "monthly":
            span_start = _month_start(cursor)
            span_end = _month_end(cursor)
            next_cursor = _add_months(span_start, 1)
        else:
            raise ReportError(f"Unsupported period: {period}")

        spans.append(PeriodSpan(start=span_start, end=min(span_end, end)))
        cursor = next_cursor
        if len(spans) > MAX_TREND_POINTS:
            break

    return spans


def _build_account_lines(
    accounts: Sequence[Account], balances: dict[UUID, Decimal], filter_type: AccountType
) -> list[dict[str, Any]]:
    items = [account for account in accounts if account.type == filter_type]
    items.sort(key=lambda acc: acc.name.lower())
    return [
        {
            "account_id": account.id,
            "name": account.name,
            "type": account.type,
            "parent_id": account.parent_id,
            "amount": _quantize_money(balances.get(account.id, Decimal("0"))),
        }
        for account in items
    ]


async def _load_accounts(db: AsyncSession, user_id: UUID, account_types: tuple[AccountType, ...]) -> list[Account]:
    result = await db.execute(
        select(Account)
        .where(Account.user_id == user_id)
        .where(Account.type.in_(account_types))
        .where(Account.is_active.is_(True))
    )
    return list(result.scalars().all())


async def generate_balance_sheet(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    currency: str | None = None,
) -> dict[str, object]:
    """Generate balance sheet report as of a given date."""
    target_currency = _normalize_currency(currency)
    account_types = (AccountType.ASSET, AccountType.LIABILITY, AccountType.EQUITY)
    accounts = await _load_accounts(db, user_id, account_types)

    balances: dict[UUID, Decimal] = {account.id: Decimal("0") for account in accounts}

    stmt = (
        select(JournalLine, Account, JournalEntry)
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(Account.type.in_(account_types))
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date <= as_of_date)
    )

    result = await db.execute(stmt)

    for line, account, _entry in result.all():
        try:
            converted = await convert_amount(
                db,
                amount=line.amount,
                currency=line.currency,
                target_currency=target_currency,
                rate_date=as_of_date,
            )
        except FxRateError as exc:
            logger.error(
                "FX conversion failed for balance sheet",
                error_id=ErrorIds.REPORT_GENERATION_FAILED,
                account_id=account.id,
                currency=line.currency,
                error=str(exc),
            )
            raise ReportError(str(exc)) from exc
        balances[account.id] += _signed_amount(account.type, line.direction, converted)

    assets = _build_account_lines(accounts, balances, AccountType.ASSET)
    liabilities = _build_account_lines(accounts, balances, AccountType.LIABILITY)
    equity = _build_account_lines(accounts, balances, AccountType.EQUITY)

    total_assets = _quantize_money(sum((Decimal(str(line["amount"])) for line in assets), Decimal("0")))
    total_liabilities = _quantize_money(sum((Decimal(str(line["amount"])) for line in liabilities), Decimal("0")))
    total_equity = _quantize_money(sum((Decimal(str(line["amount"])) for line in equity), Decimal("0")))

    # Calculate cumulative Net Income (Income - Expenses) up to as_of_date
    income_expense_stmt = (
        select(JournalLine, Account, JournalEntry)
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(Account.type.in_((AccountType.INCOME, AccountType.EXPENSE)))
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date <= as_of_date)
    )
    ie_result = await db.execute(income_expense_stmt)
    ie_rows = ie_result.all()

    # Pre-fetch all needed FX rates for historical income/expenses
    fx_rates = PrefetchedFxRates()
    fx_needs: list[tuple[str, str, date, date | None, date | None]] = []
    for ie_line, ie_account, ie_entry in ie_rows:
        if ie_line.currency != target_currency:
            fx_needs.append((ie_line.currency, target_currency, ie_entry.entry_date, None, None))

    if fx_needs:
        try:
            await fx_rates.prefetch(db, fx_needs)
        except FxRateError as exc:
            logger.error(
                "Failed to pre-fetch FX rates for balance sheet historical data",
                error_id=ErrorIds.REPORT_GENERATION_FAILED,
                error=str(exc),
            )
            # We don't raise here, individual lines will try fallback

    net_income = Decimal("0")
    for ie_line, ie_account, ie_entry in ie_rows:
        # Use pre-fetched rates for Income/Expense (historical cost)
        ie_rate = fx_rates.get_rate(ie_line.currency, target_currency, ie_entry.entry_date)
        if ie_rate is not None:
            ie_converted = ie_line.amount * ie_rate
        else:
            try:
                ie_converted = await convert_amount(
                    db,
                    amount=ie_line.amount,
                    currency=ie_line.currency,
                    target_currency=target_currency,
                    rate_date=ie_entry.entry_date,
                )
            except FxRateError as exc:
                # Fallback to spot rate if historical rate unavailable
                logger.warning(
                    "Historical FX rate unavailable for income/expense, falling back to spot rate",
                    error_id=ErrorIds.REPORT_FX_FALLBACK,
                    account_id=ie_account.id,
                    currency=ie_line.currency,
                    historical_date=ie_entry.entry_date,
                    spot_date=as_of_date,
                    error=str(exc),
                )
                try:
                    ie_converted = await convert_amount(
                        db,
                        amount=ie_line.amount,
                        currency=ie_line.currency,
                        target_currency=target_currency,
                        rate_date=as_of_date,
                    )
                except FxRateError as final_exc:
                    logger.error(
                        "All FX rate fallbacks failed for income/expense",
                        error_id=ErrorIds.REPORT_GENERATION_FAILED,
                        account_id=ie_account.id,
                        error=str(final_exc),
                    )
                    raise ReportError(f"FX conversion failed: {final_exc}") from final_exc

        net_income += _signed_amount(ie_account.type, ie_line.direction, ie_converted)

    net_income = _quantize_money(net_income)

    # Unrealized FX Gain/Loss is the plug value that balances the equation
    # Assets = Liabilities + Equity + Net Income + Unrealized FX
    total_liab_equity_inc = total_liabilities + total_equity + net_income
    unrealized_fx = _quantize_money(total_assets - total_liab_equity_inc)

    return {
        "as_of_date": as_of_date,
        "currency": target_currency,
        "assets": _build_account_lines(accounts, balances, AccountType.ASSET),
        "liabilities": _build_account_lines(accounts, balances, AccountType.LIABILITY),
        "equity": _build_account_lines(accounts, balances, AccountType.EQUITY),
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity,
        "net_income": net_income,
        "unrealized_fx_gain_loss": unrealized_fx,
        "equation_delta": Decimal("0.00"),
        "is_balanced": True,
    }


async def generate_income_statement(
    db: AsyncSession,
    user_id: UUID,
    *,
    start_date: date,
    end_date: date,
    currency: str | None = None,
    tags: list[str] | None = None,
    account_type: AccountType | None = None,
) -> dict[str, object]:
    """Generate income statement report for a date range."""
    if start_date > end_date:
        raise ReportError("start_date must be before end_date")

    target_currency = _normalize_currency(currency)

    if account_type:
        account_types = (account_type,)
    else:
        account_types = (AccountType.INCOME, AccountType.EXPENSE)

    accounts = await _load_accounts(db, user_id, account_types)
    balances: dict[UUID, Decimal] = {account.id: Decimal("0") for account in accounts}

    period_totals: dict[date, dict[str, Decimal]] = {}

    stmt = (
        select(JournalLine, Account, JournalEntry)
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(Account.type.in_(account_types))
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date >= start_date)
        .where(JournalEntry.entry_date <= end_date)
    )
    result = await db.execute(stmt)

    entries_by_id: dict[UUID, list[tuple[JournalLine, Account, JournalEntry]]] = {}
    fx_needs: list[tuple[str, str, date, date | None, date | None]] = []

    for line, account, entry in result.all():
        if entry.id not in entries_by_id:
            entries_by_id[entry.id] = []
        entries_by_id[entry.id].append((line, account, entry))

        # Collect FX needs for pre-fetching
        if line.currency != target_currency:
            # Period average need
            fx_needs.append((line.currency, target_currency, end_date, start_date, end_date))
            # Monthly average need
            period_key = _month_start(entry.entry_date)
            month_end = _add_months(period_key, 1) - timedelta(days=1)
            fx_needs.append((line.currency, target_currency, entry.entry_date, period_key, month_end))

    # Batch pre-fetch all needed FX rates
    fx_rates = PrefetchedFxRates()
    if fx_needs:
        try:
            await fx_rates.prefetch(db, fx_needs)
        except FxRateError as exc:
            logger.error(
                "FX pre-fetch failed for income statement",
                error_id=ErrorIds.REPORT_GENERATION_FAILED,
                error=str(exc),
            )
            raise ReportError(str(exc)) from exc

    entries_to_include: set[UUID] = set()
    if tags:
        for entry_id, lines_and_accounts in entries_by_id.items():
            for line, account, entry in lines_and_accounts:
                if line.tags:
                    line_tags = set(k.lower() for k in line.tags.keys())
                    if any(t.lower() in line_tags for t in tags):
                        entries_to_include.add(entry_id)
                        break
    else:
        entries_to_include = set(entries_by_id.keys())

    for entry_id, lines_and_accounts in entries_by_id.items():
        if entry_id not in entries_to_include:
            continue

        for line, account, entry in lines_and_accounts:
            # Use pre-fetched rates
            rate_total = fx_rates.get_rate(line.currency, target_currency, end_date, start_date, end_date)
            if rate_total is None:
                # Fallback to slow path if not pre-fetched (should be rare)
                try:
                    converted_total = await convert_amount(
                        db,
                        amount=line.amount,
                        currency=line.currency,
                        target_currency=target_currency,
                        rate_date=end_date,
                        average_start=start_date,
                        average_end=end_date,
                    )
                except FxRateError as exc:
                    logger.warning(
                        "Average FX rate unavailable for income statement, falling back to spot rate",
                        error_id=ErrorIds.REPORT_FX_FALLBACK,
                        account_id=account.id,
                        currency=line.currency,
                        start_date=start_date,
                        end_date=end_date,
                        error=str(exc),
                    )
                    # Fallback to spot rate at end_date
                    try:
                        converted_total = await convert_amount(
                            db,
                            amount=line.amount,
                            currency=line.currency,
                            target_currency=target_currency,
                            rate_date=end_date,
                        )
                    except FxRateError as final_exc:
                        logger.error(
                            "All FX rate fallbacks failed for income statement",
                            error_id=ErrorIds.REPORT_GENERATION_FAILED,
                            account_id=account.id,
                            error=str(final_exc),
                        )
                        raise ReportError(f"FX conversion failed: {final_exc}") from final_exc
            else:
                converted_total = line.amount * rate_total

            signed_total = _signed_amount(account.type, line.direction, converted_total)
            balances[account.id] += signed_total

            # For monthly trend buckets, use pre-fetched monthly average rate
            period_key = _month_start(entry.entry_date)
            month_end = _add_months(period_key, 1) - timedelta(days=1)
            rate_monthly = fx_rates.get_rate(line.currency, target_currency, entry.entry_date, period_key, month_end)
            if rate_monthly is None:
                # Fallback to period total rate if monthly rate unavailable
                logger.warning(
                    "Monthly average FX rate unavailable for trend, using period average",
                    error_id=ErrorIds.REPORT_FX_FALLBACK,
                    currency=line.currency,
                    month_start=period_key,
                )
                converted_monthly = converted_total
            else:
                converted_monthly = line.amount * rate_monthly

            signed_monthly = _signed_amount(account.type, line.direction, converted_monthly)
            bucket = period_totals.setdefault(period_key, {"income": Decimal("0"), "expense": Decimal("0")})
            if account.type == AccountType.INCOME:
                bucket["income"] += signed_monthly
            else:
                bucket["expense"] += signed_monthly

    income_lines = _build_account_lines(accounts, balances, AccountType.INCOME)
    expense_lines = _build_account_lines(accounts, balances, AccountType.EXPENSE)

    total_income = _quantize_money(sum((Decimal(str(line["amount"])) for line in income_lines), Decimal("0")))
    total_expenses = _quantize_money(sum((Decimal(str(line["amount"])) for line in expense_lines), Decimal("0")))
    net_income = _quantize_money(total_income - total_expenses)

    # Calculate Unrealized FX Gain/Loss for the period
    # This requires balance sheets at both points
    bs_start = await generate_balance_sheet(
        db, user_id, as_of_date=start_date - timedelta(days=1), currency=target_currency
    )
    bs_end = await generate_balance_sheet(db, user_id, as_of_date=end_date, currency=target_currency)

    unrealized_fx_change = _quantize_money(
        Decimal(str(bs_end["unrealized_fx_gain_loss"])) - Decimal(str(bs_start["unrealized_fx_gain_loss"]))
    )

    trend_items: list[dict[str, Any]] = []
    for period_start in sorted(period_totals.keys()):
        period_end = _month_end(period_start)
        income_total = _quantize_money(period_totals[period_start]["income"])
        expense_total = _quantize_money(period_totals[period_start]["expense"])
        trend_items.append(
            {
                "period_start": period_start,
                "period_end": min(period_end, end_date),
                "total_income": income_total,
                "total_expenses": expense_total,
                "net_income": _quantize_money(income_total - expense_total),
            }
        )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "currency": target_currency,
        "income": income_lines,
        "expenses": expense_lines,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_income": net_income,
        "unrealized_fx_gain_loss": unrealized_fx_change,
        "comprehensive_income": _quantize_money(net_income + unrealized_fx_change),
        "trends": trend_items,
        "filters_applied": {
            "tags": tags,
            "account_type": account_type.value if account_type else None,
        },
    }


async def get_account_trend(
    db: AsyncSession,
    user_id: UUID,
    *,
    account_id: UUID,
    period: str,
    currency: str | None = None,
) -> dict[str, object]:
    """Get account trend data for a period granularity."""
    target_currency = _normalize_currency(currency)
    account_result = await db.execute(select(Account).where(Account.id == account_id).where(Account.user_id == user_id))
    account = account_result.scalar_one_or_none()
    if not account:
        raise ReportError("Account not found")

    today = date.today()
    if period == "daily":
        start_date = today - timedelta(days=29)
    elif period == "weekly":
        start_date = today - timedelta(weeks=11)
    elif period == "monthly":
        start_date = _add_months(today.replace(day=1), -11)
    else:
        raise ReportError(f"Unsupported period: {period}")

    stmt = (
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id == account_id)
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date >= start_date)
        .where(JournalEntry.entry_date <= today)
    )
    result = await db.execute(stmt)

    spans = _iter_periods(start_date, today, period)
    totals = {span.start: Decimal("0") for span in spans}

    for line, entry in result.all():
        try:
            converted = await convert_amount(
                db,
                amount=line.amount,
                currency=line.currency,
                target_currency=target_currency,
                rate_date=entry.entry_date,
            )
        except FxRateError as exc:
            logger.error(
                "FX conversion failed for balance sheet",
                error_id=ErrorIds.REPORT_GENERATION_FAILED,
                account_id=account.id,
                currency=line.currency,
                error=str(exc),
            )
            raise ReportError(str(exc)) from exc

        key = (
            entry.entry_date
            if period == "daily"
            else entry.entry_date - timedelta(days=entry.entry_date.weekday())
            if period == "weekly"
            else _month_start(entry.entry_date)
        )
        totals.setdefault(key, Decimal("0"))
        totals[key] += _signed_amount(account.type, line.direction, converted)

    points = [
        {
            "period_start": span.start,
            "period_end": span.end,
            "amount": _quantize_money(totals.get(span.start, Decimal("0"))),
        }
        for span in spans
    ]

    return {
        "account_id": account_id,
        "currency": target_currency,
        "period": period,
        "points": points,
    }


async def get_category_breakdown(
    db: AsyncSession,
    user_id: UUID,
    *,
    breakdown_type: AccountType,
    period: str,
    currency: str | None = None,
) -> dict[str, object]:
    """Get breakdown totals by category (account) for a period."""
    if breakdown_type not in (AccountType.INCOME, AccountType.EXPENSE):
        raise ReportError("Breakdown type must be income or expense")
    target_currency = _normalize_currency(currency)
    today = date.today()

    if period == "monthly":
        start_date = _month_start(today)
    elif period == "quarterly":
        start_date = _quarter_start(today)
    elif period == "annual":
        start_date = date(today.year, 1, 1)
    else:
        raise ReportError(f"Unsupported period: {period}")

    accounts = await _load_accounts(db, user_id, (breakdown_type,))
    balances: dict[UUID, Decimal] = {account.id: Decimal("0") for account in accounts}

    stmt = (
        select(JournalLine, Account, JournalEntry)
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(Account.type == breakdown_type)
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date >= start_date)
        .where(JournalEntry.entry_date <= today)
    )
    result = await db.execute(stmt)

    for line, account, _ in result.all():
        try:
            converted = await convert_amount(
                db,
                amount=line.amount,
                currency=line.currency,
                target_currency=target_currency,
                rate_date=today,
                average_start=start_date,
                average_end=today,
            )
        except FxRateError as exc:
            logger.error(
                "FX conversion failed for category breakdown",
                error_id=ErrorIds.REPORT_GENERATION_FAILED,
                account_id=account.id,
                currency=line.currency,
                error=str(exc),
            )
            raise ReportError(str(exc)) from exc

        balances[account.id] += _signed_amount(account.type, line.direction, converted)

    items = [
        {
            "category_id": account.id,
            "category_name": account.name,
            "total": _quantize_money(balances.get(account.id, Decimal("0"))),
        }
        for account in accounts
    ]
    items = [item for item in items if item["total"] != Decimal("0.00")]
    items.sort(key=lambda item: item["total"], reverse=True)

    return {
        "type": breakdown_type,
        "currency": target_currency,
        "period_start": start_date,
        "period_end": today,
        "items": items,
    }


async def generate_cash_flow(
    db: AsyncSession,
    user_id: UUID,
    *,
    start_date: date,
    end_date: date,
    currency: str | None = None,
) -> dict[str, object]:
    """Generate cash flow statement for a date range.

    Cash flow is classified into three activities:
    - Operating: day-to-day business activities
    - Investing: purchase and sale of assets
    - Financing: changes in equity and borrowings
    """
    if start_date > end_date:
        raise ReportError("start_date must be before end_date")

    target_currency = _normalize_currency(currency)

    stmt = select(Account).where(Account.user_id == user_id).where(Account.is_active.is_(True))
    result = await db.execute(stmt)
    all_accounts = list(result.scalars().all())

    account_id_to_account = {a.id: a for a in all_accounts}

    balances_before: dict[UUID, Decimal] = {}
    balances_after: dict[UUID, Decimal] = {}

    stmt_before = (
        select(JournalLine, Account.id)
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date < start_date)
    )
    result_before = await db.execute(stmt_before)
    for line, acc_id in result_before.all():
        if acc_id not in balances_before:
            balances_before[acc_id] = Decimal("0")
        try:
            converted = await convert_amount(
                db,
                amount=line.amount,
                currency=line.currency,
                target_currency=target_currency,
                rate_date=start_date,
            )
        except FxRateError as exc:
            logger.error(
                "FX conversion failed for cash flow (before)",
                error_id=ErrorIds.REPORT_GENERATION_FAILED,
                account_id=acc_id,
                currency=line.currency,
                error=str(exc),
            )
            raise ReportError(str(exc)) from exc
        account = account_id_to_account.get(acc_id)
        if account:
            balances_before[acc_id] += _signed_amount(account.type, line.direction, converted)

    stmt_during = (
        select(JournalLine, Account.id)
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date >= start_date)
        .where(JournalEntry.entry_date <= end_date)
    )
    result_during = await db.execute(stmt_during)
    for line, acc_id in result_during.all():
        if acc_id not in balances_after:
            balances_after[acc_id] = Decimal("0")
        try:
            converted = await convert_amount(
                db,
                amount=line.amount,
                currency=line.currency,
                target_currency=target_currency,
                rate_date=end_date,
            )
        except FxRateError as exc:
            logger.error(
                "FX conversion failed for cash flow (during)",
                error_id=ErrorIds.REPORT_GENERATION_FAILED,
                account_id=acc_id,
                currency=line.currency,
                error=str(exc),
            )
            raise ReportError(str(exc)) from exc
        account = account_id_to_account.get(acc_id)
        if account:
            balances_after[acc_id] += _signed_amount(account.type, line.direction, converted)

    movements: dict[UUID, Decimal] = {}
    for acc_id in account_id_to_account:
        before = balances_before.get(acc_id, Decimal("0"))
        after = balances_after.get(acc_id, Decimal("0"))
        movements[acc_id] = after - before

    beginning_cash = Decimal("0")
    ending_cash = Decimal("0")
    # Identify cash and cash-equivalent accounts by name patterns
    # These should contribute to beginning/ending cash but NOT be categorized as Investing
    cash_keywords = ("cash", "bank", "checking", "savings", "money market", "petty cash")

    def is_cash_account(account: Account) -> bool:
        """Check if account is a cash or cash-equivalent account."""
        if account.type != AccountType.ASSET:
            return False
        name_lower = account.name.lower()
        return any(keyword in name_lower for keyword in cash_keywords)

    for acc_id, account in account_id_to_account.items():
        # Only cash accounts contribute to cash flow beginning/ending balances
        if is_cash_account(account):
            beginning_cash += balances_before.get(acc_id, Decimal("0"))
            ending_cash += balances_after.get(acc_id, Decimal("0"))

    operating_items: list[dict[str, object]] = []
    investing_items: list[dict[str, object]] = []
    financing_items: list[dict[str, object]] = []

    for acc_id, movement in movements.items():
        if movement == Decimal("0"):
            continue
        account = account_id_to_account[acc_id]
        abs_movement = abs(movement)
        item = {
            "category": "",
            "subcategory": account.name,
            "amount": _quantize_money(abs_movement),
            "description": f"{'Inflow' if movement > 0 else 'Outflow'} - {account.name}",
        }
        if account.type in (AccountType.INCOME, AccountType.EXPENSE):
            item["category"] = "Operating"
            operating_items.append(item)
        elif account.type == AccountType.ASSET:
            # Cash accounts are excluded from activity categories (they ARE the cash flow)
            # Non-cash assets (investments, equipment, etc.) go to Investing
            if is_cash_account(account):
                continue  # Skip cash accounts - they're reflected in net cash flow
            item["category"] = "Investing"
            investing_items.append(item)
        else:
            item["category"] = "Financing"
            financing_items.append(item)

    operating_items.sort(key=lambda x: Decimal(str(x["amount"])), reverse=True)
    investing_items.sort(key=lambda x: Decimal(str(x["amount"])), reverse=True)
    financing_items.sort(key=lambda x: Decimal(str(x["amount"])), reverse=True)

    operating_total = _quantize_money(sum([Decimal(str(item["amount"])) for item in operating_items], Decimal("0")))
    investing_total = _quantize_money(sum([Decimal(str(item["amount"])) for item in investing_items], Decimal("0")))
    financing_total = _quantize_money(sum([Decimal(str(item["amount"])) for item in financing_items], Decimal("0")))
    net_cash_flow = _quantize_money(ending_cash - beginning_cash)

    summary = {
        "operating_activities": operating_total,
        "investing_activities": investing_total,
        "financing_activities": financing_total,
        "net_cash_flow": net_cash_flow,
        "beginning_cash": _quantize_money(beginning_cash),
        "ending_cash": _quantize_money(ending_cash),
    }

    return {
        "start_date": start_date,
        "end_date": end_date,
        "currency": target_currency,
        "operating": operating_items,
        "investing": investing_items,
        "financing": financing_items,
        "summary": summary,
    }
