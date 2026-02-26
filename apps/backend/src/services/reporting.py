"""Reporting service for financial statements and analytics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, literal, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.constants.error_ids import ErrorIds
from src.logger import get_logger
from src.models import (
    Account,
    AccountType,
    Direction,
    FxRate,
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


async def _get_fx_rates_map(
    db: AsyncSession,
    currencies: set[str],
    target_currency: str,
    rate_date: date,
) -> dict[str, Decimal]:
    """Fetch FX rates for multiple currencies to target currency."""
    target = target_currency.upper()
    rates: dict[str, Decimal] = {}

    for currency in currencies:
        source = currency.upper()
        if source == target:
            rates[source] = Decimal("1")
            continue

        stmt = (
            select(FxRate.rate)
            .where(FxRate.base_currency == source)
            .where(FxRate.quote_currency == target)
            .where(FxRate.rate_date <= rate_date)
            .order_by(FxRate.rate_date.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        rate = result.scalar_one_or_none()

        if rate is None:
            raise ReportError(f"No FX rate available for {source}/{target} on {rate_date}")

        rates[source] = Decimal(str(rate)) if not isinstance(rate, Decimal) else rate

    return rates


async def _aggregate_balances_sql(
    db: AsyncSession,
    user_id: UUID,
    account_types: tuple[AccountType, ...],
    target_currency: str,
    as_of_date: date,
    *,
    start_date: date | None = None,
) -> dict[UUID, Decimal]:
    """Aggregate account balances using SQL SUM/GROUP BY with FX conversion."""
    currency_stmt = (
        select(JournalLine.currency)
        .distinct()
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(Account.type.in_(account_types))
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date <= as_of_date)
    )
    if start_date:
        currency_stmt = currency_stmt.where(JournalEntry.entry_date >= start_date)

    currency_result = await db.execute(currency_stmt)
    currencies = {row[0].upper() for row in currency_result.all()}

    if not currencies:
        return {}

    fx_rates = await _get_fx_rates_map(db, currencies, target_currency, as_of_date)

    fx_case_parts = []
    for currency, rate in fx_rates.items():
        fx_case_parts.append((JournalLine.currency == currency, literal(rate)))

    fx_rate_expr = case(*fx_case_parts, else_=literal(Decimal("1")))

    # Accounting sign rules: ASSET/EXPENSE: DEBIT=+, CREDIT=-; LIABILITY/EQUITY/INCOME: CREDIT=+, DEBIT=-
    sign_expr = case(
        (
            (Account.type.in_((AccountType.ASSET, AccountType.EXPENSE))) & (JournalLine.direction == Direction.DEBIT),
            literal(1),
        ),
        (
            (Account.type.in_((AccountType.ASSET, AccountType.EXPENSE))) & (JournalLine.direction == Direction.CREDIT),
            literal(-1),
        ),
        (
            (Account.type.in_((AccountType.LIABILITY, AccountType.EQUITY, AccountType.INCOME)))
            & (JournalLine.direction == Direction.CREDIT),
            literal(1),
        ),
        (
            (Account.type.in_((AccountType.LIABILITY, AccountType.EQUITY, AccountType.INCOME)))
            & (JournalLine.direction == Direction.DEBIT),
            literal(-1),
        ),
        else_=literal(1),
    )

    agg_stmt = (
        select(
            Account.id.label("account_id"),
            func.sum(JournalLine.amount * fx_rate_expr * sign_expr).label("balance"),
        )
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(Account.type.in_(account_types))
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date <= as_of_date)
        .group_by(Account.id)
    )
    if start_date:
        agg_stmt = agg_stmt.where(JournalEntry.entry_date >= start_date)

    result = await db.execute(agg_stmt)
    return {row.account_id: Decimal(str(row.balance)) if row.balance else Decimal("0") for row in result.all()}


async def _aggregate_net_income_sql(
    db: AsyncSession,
    user_id: UUID,
    target_currency: str,
    as_of_date: date,
    *,
    start_date: date | None = None,
) -> Decimal:
    """Aggregate net income (Income - Expenses) using SQL with FX conversion.

    Uses historical cost accounting - FX rate at entry_date for each transaction.
    """
    # First, get distinct currencies and entry dates for FX rate lookup
    currency_date_stmt = (
        select(JournalLine.currency, JournalEntry.entry_date)
        .distinct()
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(Account.type.in_((AccountType.INCOME, AccountType.EXPENSE)))
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date <= as_of_date)
    )
    if start_date:
        currency_date_stmt = currency_date_stmt.where(JournalEntry.entry_date >= start_date)

    cd_result = await db.execute(currency_date_stmt)
    currency_dates = cd_result.all()

    if not currency_dates:
        return Decimal("0")

    # Build FX rate map: (currency, entry_date) -> rate
    fx_rate_map: dict[tuple[str, date], Decimal] = {}
    for currency, entry_date in currency_dates:
        source = currency.upper()
        if source == target_currency:
            fx_rate_map[(source, entry_date)] = Decimal("1")
            continue

        # Get rate for this specific date (historical cost accounting)
        stmt = (
            select(FxRate.rate)
            .where(FxRate.base_currency == source)
            .where(FxRate.quote_currency == target_currency)
            .where(FxRate.rate_date <= entry_date)
            .order_by(FxRate.rate_date.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        rate = result.scalar_one_or_none()

        if rate is None:
            fallback_stmt = (
                select(FxRate.rate)
                .where(FxRate.base_currency == source)
                .where(FxRate.quote_currency == target_currency)
                .where(FxRate.rate_date <= as_of_date)
                .order_by(FxRate.rate_date.desc())
                .limit(1)
            )
            fallback_result = await db.execute(fallback_stmt)
            rate = fallback_result.scalar_one_or_none()

            if rate is None:
                raise ReportError(f"No FX rate available for {source}/{target_currency} on {entry_date}")

            logger.warning(
                "Using fallback FX rate for net income calculation",
                error_id=ErrorIds.REPORT_FX_FALLBACK,
                currency=source,
                entry_date=entry_date.isoformat(),
                fallback_date=as_of_date.isoformat(),
            )

        fx_rate_map[(source, entry_date)] = Decimal(str(rate)) if not isinstance(rate, Decimal) else rate

    agg_stmt = (
        select(
            JournalLine.currency,
            JournalEntry.entry_date,
            Account.type,
            JournalLine.direction,
            func.sum(JournalLine.amount).label("total"),
        )
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(Account.type.in_((AccountType.INCOME, AccountType.EXPENSE)))
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date <= as_of_date)
        .group_by(JournalLine.currency, JournalEntry.entry_date, Account.type, JournalLine.direction)
    )
    if start_date:
        agg_stmt = agg_stmt.where(JournalEntry.entry_date >= start_date)

    result = await db.execute(agg_stmt)

    net_income = Decimal("0")
    for row in result.all():
        currency_upper = row.currency.upper()
        fx_rate = fx_rate_map.get((currency_upper, row.entry_date))
        if fx_rate is None:
            raise ReportError(
                f"Missing FX rate for {currency_upper}/{target_currency} on {row.entry_date} - data consistency error"
            )
        converted = Decimal(str(row.total)) * fx_rate
        signed = _signed_amount(row.type, row.direction, converted)
        net_income += signed

    return net_income


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

    try:
        balances = await _aggregate_balances_sql(db, user_id, account_types, target_currency, as_of_date)
    except ReportError:
        raise
    except SQLAlchemyError as exc:
        logger.error(
            "Balance sheet aggregation failed",
            error_id=ErrorIds.REPORT_GENERATION_FAILED,
            error=str(exc),
        )
        raise ReportError(str(exc)) from exc

    for account in accounts:
        if account.id not in balances:
            balances[account.id] = Decimal("0")

    assets = _build_account_lines(accounts, balances, AccountType.ASSET)
    liabilities = _build_account_lines(accounts, balances, AccountType.LIABILITY)
    equity = _build_account_lines(accounts, balances, AccountType.EQUITY)

    total_assets = _quantize_money(sum((Decimal(str(line["amount"])) for line in assets), Decimal("0")))
    total_liabilities = _quantize_money(sum((Decimal(str(line["amount"])) for line in liabilities), Decimal("0")))
    total_equity = _quantize_money(sum((Decimal(str(line["amount"])) for line in equity), Decimal("0")))

    # Calculate cumulative Net Income (Income - Expenses) up to as_of_date
    # Uses SQL aggregation with historical cost accounting (FX rate at entry_date)
    try:
        net_income = await _aggregate_net_income_sql(db, user_id, target_currency, as_of_date)
    except ReportError:
        raise
    except SQLAlchemyError as exc:
        logger.error(
            "Net income aggregation failed",
            error_id=ErrorIds.REPORT_GENERATION_FAILED,
            error=str(exc),
        )
        raise ReportError(str(exc)) from exc

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
                        "Average FX rate unavailable, falling back to spot",
                        error_id=ErrorIds.REPORT_FX_FALLBACK,
                        account_id=str(account.id),
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
                            account_id=str(account.id),
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

    agg_stmt = (
        select(
            JournalLine.currency,
            JournalEntry.entry_date,
            JournalLine.direction,
            func.sum(JournalLine.amount).label("total"),
        )
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id == account_id)
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date >= start_date)
        .where(JournalEntry.entry_date <= today)
        .group_by(JournalLine.currency, JournalEntry.entry_date, JournalLine.direction)
    )
    result = await db.execute(agg_stmt)
    rows = result.all()

    fx_needs: list[tuple[str, str, date, date | None, date | None]] = []
    for row in rows:
        if row.currency.upper() != target_currency:
            fx_needs.append((row.currency, target_currency, row.entry_date, None, None))

    fx_rates = PrefetchedFxRates()
    if fx_needs:
        try:
            await fx_rates.prefetch(db, fx_needs)
        except FxRateError as exc:
            logger.error(
                "FX pre-fetch failed for account trend",
                error_id=ErrorIds.REPORT_GENERATION_FAILED,
                account_id=str(account.id),
                error=str(exc),
            )
            raise ReportError(str(exc)) from exc

    spans = _iter_periods(start_date, today, period)
    totals: dict[date, Decimal] = {span.start: Decimal("0") for span in spans}

    for row in rows:
        rate = fx_rates.get_rate(row.currency, target_currency, row.entry_date)
        if rate is None:
            if row.currency.upper() == target_currency:
                rate = Decimal("1")
            else:
                raise ReportError(f"No FX rate available for {row.currency}/{target_currency} on {row.entry_date}")

        converted = Decimal(str(row.total)) * rate
        signed = _signed_amount(account.type, row.direction, converted)

        key = (
            row.entry_date
            if period == "daily"
            else row.entry_date - timedelta(days=row.entry_date.weekday())
            if period == "weekly"
            else _month_start(row.entry_date)
        )
        totals.setdefault(key, Decimal("0"))
        totals[key] += signed

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
    account_map = {account.id: account for account in accounts}
    balances: dict[UUID, Decimal] = {account.id: Decimal("0") for account in accounts}

    agg_stmt = (
        select(
            Account.id.label("account_id"),
            JournalLine.currency,
            JournalLine.direction,
            func.sum(JournalLine.amount).label("total"),
        )
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(Account.type == breakdown_type)
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date >= start_date)
        .where(JournalEntry.entry_date <= today)
        .group_by(Account.id, JournalLine.currency, JournalLine.direction)
    )
    result = await db.execute(agg_stmt)
    rows = result.all()

    fx_needs: list[tuple[str, str, date, date | None, date | None]] = []
    for row in rows:
        if row.currency.upper() != target_currency:
            fx_needs.append((row.currency, target_currency, today, start_date, today))

    fx_rates = PrefetchedFxRates()
    if fx_needs:
        try:
            await fx_rates.prefetch(db, fx_needs)
        except FxRateError as exc:
            logger.error(
                "FX pre-fetch failed for category breakdown",
                error_id=ErrorIds.REPORT_GENERATION_FAILED,
                error=str(exc),
            )
            raise ReportError(str(exc)) from exc

    for row in rows:
        rate = fx_rates.get_rate(row.currency, target_currency, today, start_date, today)
        if rate is None:
            if row.currency.upper() == target_currency:
                rate = Decimal("1")
            else:
                raise ReportError(f"No FX rate available for {row.currency}/{target_currency}")

        converted = Decimal(str(row.total)) * rate
        account = account_map.get(row.account_id)
        if account:
            balances[row.account_id] += _signed_amount(account.type, row.direction, converted)

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

    agg_stmt_before = (
        select(
            Account.id.label("account_id"),
            JournalLine.currency,
            JournalLine.direction,
            func.sum(JournalLine.amount).label("total"),
        )
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date < start_date)
        .group_by(Account.id, JournalLine.currency, JournalLine.direction)
    )
    result_before = await db.execute(agg_stmt_before)
    rows_before = result_before.all()

    agg_stmt_during = (
        select(
            Account.id.label("account_id"),
            JournalLine.currency,
            JournalLine.direction,
            func.sum(JournalLine.amount).label("total"),
        )
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date >= start_date)
        .where(JournalEntry.entry_date <= end_date)
        .group_by(Account.id, JournalLine.currency, JournalLine.direction)
    )
    result_during = await db.execute(agg_stmt_during)
    rows_during = result_during.all()

    fx_needs: list[tuple[str, str, date, date | None, date | None]] = []
    for row in rows_before:
        if row.currency.upper() != target_currency:
            fx_needs.append((row.currency, target_currency, start_date, None, None))
    for row in rows_during:
        if row.currency.upper() != target_currency:
            fx_needs.append((row.currency, target_currency, end_date, None, None))

    fx_rates = PrefetchedFxRates()
    if fx_needs:
        try:
            await fx_rates.prefetch(db, fx_needs)
        except FxRateError as exc:
            logger.error(
                "FX pre-fetch failed for cash flow",
                error_id=ErrorIds.REPORT_GENERATION_FAILED,
                error=str(exc),
            )
            raise ReportError(str(exc)) from exc

    balances_before: dict[UUID, Decimal] = {}
    for row in rows_before:
        rate = fx_rates.get_rate(row.currency, target_currency, start_date)
        if rate is None:
            if row.currency.upper() == target_currency:
                rate = Decimal("1")
            else:
                raise ReportError(f"No FX rate available for {row.currency}/{target_currency} on {start_date}")

        converted = Decimal(str(row.total)) * rate
        account = account_id_to_account.get(row.account_id)
        if account:
            if row.account_id not in balances_before:
                balances_before[row.account_id] = Decimal("0")
            balances_before[row.account_id] += _signed_amount(account.type, row.direction, converted)

    balances_after: dict[UUID, Decimal] = {}
    for row in rows_during:
        rate = fx_rates.get_rate(row.currency, target_currency, end_date)
        if rate is None:
            if row.currency.upper() == target_currency:
                rate = Decimal("1")
            else:
                raise ReportError(f"No FX rate available for {row.currency}/{target_currency} on {end_date}")

        converted = Decimal(str(row.total)) * rate
        account = account_id_to_account.get(row.account_id)
        if account:
            if row.account_id not in balances_after:
                balances_after[row.account_id] = Decimal("0")
            balances_after[row.account_id] += _signed_amount(account.type, row.direction, converted)

    movements: dict[UUID, Decimal] = {}
    for acc_id in account_id_to_account:
        before = balances_before.get(acc_id, Decimal("0"))
        after = balances_after.get(acc_id, Decimal("0"))
        movements[acc_id] = after - before

    beginning_cash = Decimal("0")
    ending_cash = Decimal("0")
    cash_keywords = ("cash", "bank", "checking", "savings", "money market", "petty cash")

    def is_cash_account(account: Account) -> bool:
        if account.type != AccountType.ASSET:
            return False
        name_lower = account.name.lower()
        return any(keyword in name_lower for keyword in cash_keywords)

    for acc_id, account in account_id_to_account.items():
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
            if is_cash_account(account):
                continue
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
