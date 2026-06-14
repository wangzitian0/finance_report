"""Reporting service for financial statements and analytics."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast
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
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.models.layer3 import (
    ManagedPosition,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    PositionStatus,
)
from src.schemas.provenance import DataProvenance
from src.services import fx
from src.services.assets import AssetService
from src.services.confidence_tier import derive_confidence_tier
from src.services.fx import (
    FxRateError,
    FxWarning,
    PrefetchedFxRates,
    convert_amount,
    get_average_rate,
    get_exchange_rate,
)
from src.services.fx_revaluation import RevaluationError, calculate_unrealized_fx_gains
from src.services.portfolio import AssetNotFoundError, PortfolioService
from src.utils.money import to_money

logger = get_logger(__name__)

_REPORT_STATUSES = (JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED)
_IMPORTED_SOURCE_TYPES = {
    JournalEntrySourceType.AUTO_PARSED,
    JournalEntrySourceType.AUTO_MATCHED,
    JournalEntrySourceType.USER_CONFIRMED,
    JournalEntrySourceType.BANK_STATEMENT,
}
_MANUAL_SOURCE_TYPES = {JournalEntrySourceType.MANUAL}
_DERIVED_SOURCE_TYPES = {JournalEntrySourceType.SYSTEM, JournalEntrySourceType.FX_REVALUATION}
_ALLOCATION_METADATA_KEYS = {
    "source_currency",
    "allocation_asset_class",
    "allocation_liquidity_class",
    "allocation_source_type",
}


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


def income_bucket(account_name: str) -> str | None:
    normalized = account_name.casefold()
    if "salary" in normalized or "payroll" in normalized:
        return "salary"
    if "bonus" in normalized:
        return "bonus"
    if "dividend" in normalized:
        return "dividend"
    return None


def _quantize_money(amount: Decimal | int) -> Decimal:
    if isinstance(amount, int):
        amount = Decimal(amount)
    return to_money(amount)


def _provenance_from_source_type(source_type: JournalEntrySourceType | str | None) -> DataProvenance | None:
    if source_type is None:
        return None
    try:
        normalized = (
            source_type if isinstance(source_type, JournalEntrySourceType) else JournalEntrySourceType(source_type)
        )
    except ValueError:
        return None
    if normalized in _MANUAL_SOURCE_TYPES:
        return "manual"
    if normalized in _IMPORTED_SOURCE_TYPES:
        return "imported"
    if normalized in _DERIVED_SOURCE_TYPES:
        return "derived"
    return None


def _combine_provenance(values: Sequence[DataProvenance | None]) -> DataProvenance | None:
    known = {value for value in values if value is not None}
    if not known:
        return None
    if len(known) == 1:
        return next(iter(known))
    return "derived"


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
MAX_NET_WORTH_DAILY_POINTS = 366


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


# Confidence tiers ranked by trust (vision Axiom B). The worst-input rule rolls a
# line/aggregate down to its least-trusted contributor — a defined rollup, never
# an invented number.
_CONFIDENCE_TIER_RANK: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "TRUSTED": 3}


def _worst_confidence_tier(tiers: Iterable[str | None]) -> str | None:
    """Return the least-trusted tier among the inputs, or None if none are rated."""
    present = [tier for tier in tiers if tier]
    if not present:
        return None
    return min(present, key=lambda tier: _CONFIDENCE_TIER_RANK.get(tier, 0))


def _build_account_lines(
    accounts: Sequence[Account],
    balances: dict[UUID, Decimal],
    filter_type: AccountType,
    tiers: dict[UUID, str] | None = None,
    provenance_by_account: dict[UUID, DataProvenance | None] | None = None,
) -> list[dict[str, Any]]:
    tiers = tiers or {}
    items = [account for account in accounts if account.type == filter_type]
    items.sort(key=lambda acc: acc.name.lower())
    return [
        {
            "account_id": account.id,
            "name": account.name,
            "type": account.type,
            "parent_id": account.parent_id,
            "amount": _quantize_money(balances.get(account.id, Decimal("0"))),
            "confidence_tier": tiers.get(account.id),
            "provenance": provenance_by_account.get(account.id) if provenance_by_account is not None else None,
            "source_currency": account.currency.upper(),
            "allocation_asset_class": _ledger_allocation_asset_class(account),
            "allocation_liquidity_class": _ledger_allocation_liquidity_class(account),
            "allocation_source_type": "ledger_account",
        }
        for account in items
    ]


async def _aggregate_account_confidence_tiers(
    db: AsyncSession,
    user_id: UUID,
    account_types: tuple[AccountType, ...],
    as_of_date: date,
    *,
    start_date: date | None = None,
    included_currencies: set[str] | None = None,
) -> dict[UUID, str]:
    """Per-account worst-input confidence tier, derived from contributing entries' source_type."""
    if included_currencies is not None and not included_currencies:
        return {}

    stmt = (
        select(Account.id, JournalEntry.source_type)
        .distinct()
        .select_from(JournalLine)
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(Account.type.in_(account_types))
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date <= as_of_date)
    )
    if start_date:
        stmt = stmt.where(JournalEntry.entry_date >= start_date)
    if included_currencies is not None:
        stmt = stmt.where(JournalLine.currency.in_(list(included_currencies)))

    result = await db.execute(stmt)
    tiers: dict[UUID, str] = {}
    for account_id, source_type in result.all():
        tier = derive_confidence_tier(source_type)
        tiers[account_id] = _worst_confidence_tier([tiers.get(account_id), tier]) or tier
    return tiers


def _line_total(lines: Sequence[dict[str, Any]]) -> Decimal:
    return _quantize_money(sum((Decimal(str(line["amount"])) for line in lines), Decimal("0")))


def _strip_allocation_metadata(lines: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in line.items() if key not in _ALLOCATION_METADATA_KEYS} for line in lines]


def _valuation_line_name(component_name: str, component_type: str) -> str:
    label = component_type.replace("_", " ")
    return f"Valuation: {component_name} ({label})"


def _ledger_allocation_asset_class(account: Account) -> str:
    if account.type == AccountType.LIABILITY:
        return "liability"
    if account.type == AccountType.ASSET:
        return "cash"
    return "other"


def _ledger_allocation_liquidity_class(account: Account) -> str:
    if account.type == AccountType.LIABILITY:
        return ManualValuationLiquidityClass.LIABILITY.value
    return ManualValuationLiquidityClass.LIQUID.value


def _manual_valuation_allocation_asset_class(component_type: str) -> str:
    if component_type in {
        ManualValuationComponentType.PROPERTY_VALUE.value,
        ManualValuationComponentType.MORTGAGE_BALANCE.value,
    }:
        return "real_estate"
    if component_type in {
        ManualValuationComponentType.ESOP.value,
        ManualValuationComponentType.RSU.value,
        ManualValuationComponentType.STOCK_OPTIONS.value,
    }:
        return "restricted_comp"
    if component_type == ManualValuationComponentType.TAX_REFUND.value:
        return "cash"
    if component_type in {
        ManualValuationComponentType.TAX_PAYABLE.value,
        ManualValuationComponentType.OTHER_LIABILITY.value,
    }:
        return "liability"
    return "other"


def _single_source_currency(source_currencies: set[str], target_currency: str) -> str:
    if len(source_currencies) == 1:
        return next(iter(source_currencies))
    return target_currency


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
    *,
    fx_warnings: list[FxWarning] | None = None,
) -> dict[str, Decimal]:
    """Fetch FX rates for multiple currencies to target currency."""
    target = target_currency.upper()
    rates: dict[str, Decimal] = {}

    for currency in currencies:
        source = currency.upper()
        if source == target:
            rates[source] = Decimal("1")
            continue

        try:
            rates[source] = await get_exchange_rate(db, source, target, rate_date, lazy_load=True)
        except FxRateError as exc:
            warning = {
                "type": "missing_fx_rate_partial_skip",
                "base_currency": source,
                "quote_currency": target,
                "rate_date": rate_date.isoformat(),
            }
            if fx_warnings is not None and warning not in fx_warnings:
                fx_warnings.append(warning)
            logger.warning(
                "Skipping unconvertible reporting currency because FX rate is unavailable",
                error_id=ErrorIds.REPORT_FX_FALLBACK,
                currency=source,
                target_currency=target,
                rate_date=rate_date.isoformat(),
                error=str(exc),
            )

    return rates


async def _aggregate_balances_sql(
    db: AsyncSession,
    user_id: UUID,
    account_types: tuple[AccountType, ...],
    target_currency: str,
    as_of_date: date,
    *,
    start_date: date | None = None,
    fx_warnings: list[FxWarning] | None = None,
    included_currencies: set[str] | None = None,
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

    fx_rates = await _get_fx_rates_map(db, currencies, target_currency, as_of_date, fx_warnings=fx_warnings)
    if not fx_rates:
        return {}
    if included_currencies is not None:
        included_currencies.update(fx_rates.keys())

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
        .where(JournalLine.currency.in_(list(fx_rates.keys())))
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date <= as_of_date)
        .group_by(Account.id)
    )
    if start_date:
        agg_stmt = agg_stmt.where(JournalEntry.entry_date >= start_date)

    result = await db.execute(agg_stmt)
    return {row.account_id: Decimal(str(row.balance)) if row.balance else Decimal("0") for row in result.all()}


async def _aggregate_account_provenance(
    db: AsyncSession,
    user_id: UUID,
    account_types: tuple[AccountType, ...],
    as_of_date: date,
    *,
    start_date: date | None = None,
    included_currencies: set[str] | None = None,
) -> dict[UUID, DataProvenance | None]:
    """Aggregate normalized provenance per account for report line read models."""
    if included_currencies is not None and not included_currencies:
        return {}

    stmt = (
        select(Account.id.label("account_id"), JournalEntry.source_type)
        # Distinct (account, source_type): provenance only needs the set, not one row per line.
        .distinct()
        .join(JournalLine, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(Account.type.in_(account_types))
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date <= as_of_date)
    )
    if start_date:
        stmt = stmt.where(JournalEntry.entry_date >= start_date)
    if included_currencies is not None:
        stmt = stmt.where(JournalLine.currency.in_(list(included_currencies)))

    result = await db.execute(stmt)
    provenance_inputs: dict[UUID, list[DataProvenance | None]] = {}
    for row in result.all():
        provenance_inputs.setdefault(row.account_id, []).append(_provenance_from_source_type(row.source_type))
    return {
        account_id: _combine_provenance(provenance_values)
        for account_id, provenance_values in provenance_inputs.items()
    }


async def get_account_lineage(
    db: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    *,
    as_of_date: date,
    start_date: date | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    """Return the posted/reconciled journal lines behind one account's balance.

    Mirrors the balance-sheet aggregation filters (status, as_of_date, optional
    start_date) but keeps lines disaggregated so each contributing line exposes
    a ``journal_line`` evidence anchor for drill-down. Amounts are signed using
    the same accounting rules and converted into the report currency.
    """
    account = await db.scalar(select(Account).where(Account.id == account_id).where(Account.user_id == user_id))
    if account is None:
        raise ReportError(f"Account {account_id} not found")

    target_currency = _normalize_currency(currency or account.currency)

    line_stmt = (
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id == account_id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date <= as_of_date)
        .order_by(JournalEntry.entry_date.desc(), JournalLine.created_at.desc())
    )
    if start_date:
        line_stmt = line_stmt.where(JournalEntry.entry_date >= start_date)

    rows = (await db.execute(line_stmt)).all()
    currencies = {line.currency.upper() for line, _entry in rows}
    fx_rates = await _get_fx_rates_map(db, currencies, target_currency, as_of_date) if currencies else {}

    lines: list[dict[str, Any]] = []
    total = Decimal("0")
    for line, entry in rows:
        rate = fx_rates.get(line.currency.upper(), Decimal("1"))
        signed = _quantize_money(_signed_amount(account.type, line.direction, line.amount) * rate)
        total += signed
        lines.append(
            {
                "journal_line_id": line.id,
                "journal_entry_id": entry.id,
                "entry_date": entry.entry_date,
                "memo": entry.memo,
                "direction": line.direction,
                "original_amount": line.amount,
                "original_currency": line.currency,
                "amount": signed,
            }
        )

    return {
        "account_id": account.id,
        "account_name": account.name,
        "account_type": account.type,
        "currency": target_currency,
        "as_of_date": as_of_date,
        "start_date": start_date,
        "total": _quantize_money(total),
        "lines": lines,
    }


async def _aggregate_net_income_sql(
    db: AsyncSession,
    user_id: UUID,
    target_currency: str,
    as_of_date: date,
    *,
    start_date: date | None = None,
    fx_warnings: list[FxWarning] | None = None,
) -> Decimal:
    """Aggregate net income (Income - Expenses) using SQL with period-average FX conversion.

    Uses period-average FX rates matching the income statement reporting convention.
    When start_date is omitted (cumulative balance sheet use), the average spans all
    available historical FX rates up to as_of_date (sentinel: 1970-01-01).
    If no FX rates exist in the range, get_average_rate falls back to the most recent
    spot rate on or before as_of_date; if that is also absent, FxRateError is raised
    and re-raised here as ReportError.
    """
    # Get distinct currencies for income/expense lines in the period
    currency_stmt = (
        select(JournalLine.currency)
        .distinct()
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(Account.type.in_((AccountType.INCOME, AccountType.EXPENSE)))
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date <= as_of_date)
    )
    if start_date:
        currency_stmt = currency_stmt.where(JournalEntry.entry_date >= start_date)

    currency_result = await db.execute(currency_stmt)
    currencies = {row[0].upper() for row in currency_result.all()}

    if not currencies:
        return Decimal("0")

    # Determine the effective period start for average rate calculation.
    # When no start_date is supplied (cumulative balance sheet), use date.min
    # so the average spans ALL available FX rate history up to as_of_date.
    # This keeps the BS and IS rates aligned: when the IS covers the same
    # period, get_average_rate will see the same set of rate rows.
    # Note: get_average_rate handles sparse data by falling back to the
    # period-end spot rate when no rows exist in [date.min, as_of_date],
    # so passing date.min is safe even if the DB has no ancient rate records.
    effective_start = start_date if start_date is not None else date.min

    # Build FX rate map: currency -> average rate for the period
    fx_rate_map: dict[str, Decimal] = {}
    for source in currencies:
        if source == target_currency:
            fx_rate_map[source] = Decimal("1")
            continue

        try:
            rate = await get_average_rate(
                db,
                source,
                target_currency,
                effective_start,
                as_of_date,
                fx_warnings=fx_warnings,
                lazy_load=True,
            )
        except FxRateError as exc:
            raise ReportError(str(exc)) from exc

        fx_rate_map[source] = rate

    # Aggregate amounts grouped by currency, account type, and direction.
    # No grouping by entry_date — the same period-average rate applies to all entries.
    agg_stmt = (
        select(
            JournalLine.currency,
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
        .group_by(JournalLine.currency, Account.type, JournalLine.direction)
    )
    if start_date:
        agg_stmt = agg_stmt.where(JournalEntry.entry_date >= start_date)

    result = await db.execute(agg_stmt)

    net_income = Decimal("0")
    for row in result.all():
        currency_upper = row.currency.upper()
        fx_rate = fx_rate_map.get(currency_upper)
        if fx_rate is None:
            raise ReportError(f"Missing FX rate for {currency_upper}/{target_currency} - data consistency error")
        converted = Decimal(str(row.total)) * fx_rate
        # Net income sign convention: both income and expense types are credit-normal.
        # - Income CREDIT = +, Income DEBIT = -
        # - Expense DEBIT = - (expenses reduce net income), Expense CREDIT = +
        # Do NOT use _signed_amount here: it returns +amount for EXPENSE DEBIT (account-balance
        # convention), which is the opposite of what the net-income formula needs.
        signed = converted if row.direction == Direction.CREDIT else -converted
        net_income += signed

    return net_income


async def _portfolio_market_basis_by_account(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    target_currency: str,
) -> dict[UUID, dict[str, Any]]:
    """Return converted portfolio market/cost-basis totals by broker account."""
    portfolio_service = PortfolioService()
    portfolio_eval_date = as_of_date
    if as_of_date == date.today():
        portfolio_eval_date = await portfolio_service._default_holdings_eval_date(db, user_id)

    result = await db.execute(
        select(ManagedPosition, Account)
        .join(Account, ManagedPosition.account_id == Account.id)
        .where(ManagedPosition.user_id == user_id)
        .where(ManagedPosition.status == PositionStatus.ACTIVE)
        .where(Account.user_id == user_id)
        .where(Account.is_active.is_(True))
    )

    basis_by_account: dict[UUID, dict[str, Any]] = {}

    for position, account in result.all():
        try:
            latest_price = await portfolio_service._get_latest_price(db, position, portfolio_eval_date, user_id)
        except AssetNotFoundError:
            logger.debug(
                "Skipping portfolio valuation without market price",
                position_id=str(position.id),
                asset_identifier=position.asset_identifier,
                as_of_date=portfolio_eval_date.isoformat(),
            )
            continue

        market_value = position.quantity * latest_price
        cost_basis = position.cost_basis
        source_currency = position.currency.upper()
        if source_currency != target_currency:
            try:
                market_value = await fx.convert_amount(
                    db,
                    amount=market_value,
                    currency=source_currency,
                    target_currency=target_currency,
                    rate_date=portfolio_eval_date,
                    lazy_load=True,
                )
                cost_basis = await fx.convert_amount(
                    db,
                    amount=cost_basis,
                    currency=source_currency,
                    target_currency=target_currency,
                    rate_date=position.acquisition_date,
                    lazy_load=True,
                )
            except FxRateError as exc:
                raise ReportError(str(exc)) from exc

        basis = basis_by_account.setdefault(
            position.account_id,
            {
                "account": account,
                "market_value": Decimal("0"),
                "cost_basis": Decimal("0"),
                "source_currencies": set(),
            },
        )
        basis["market_value"] = Decimal(str(basis["market_value"])) + market_value
        basis["cost_basis"] = Decimal(str(basis["cost_basis"])) + cost_basis
        basis["source_currencies"].add(source_currency)

    return basis_by_account


async def _build_portfolio_market_adjustment_lines(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    target_currency: str,
    asset_lines: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build market-value adjustment lines for active portfolio positions.

    Ledger journal lines often carry investment purchases at cost, while the
    same brokerage account can also hold cash. Portfolio snapshots carry
    current market value. Reporting includes market value minus the position
    cost basis only when that cost basis is already represented in the ledger,
    so cash balances are not accidentally netted out.
    """
    ledger_by_account = {line["account_id"]: Decimal(str(line["amount"])) for line in asset_lines}
    basis_by_account = await _portfolio_market_basis_by_account(
        db,
        user_id,
        as_of_date=as_of_date,
        target_currency=target_currency,
    )

    adjustment_lines: list[dict[str, Any]] = []
    for account_id, basis in basis_by_account.items():
        market_value = Decimal(str(basis["market_value"]))
        ledger_value = ledger_by_account.get(account_id, Decimal("0"))
        cost_basis = Decimal(str(basis["cost_basis"]))
        ledger_cost_basis = cost_basis if ledger_value >= cost_basis else Decimal("0")
        adjustment = _quantize_money(market_value - ledger_cost_basis)
        if adjustment == Decimal("0.00"):
            continue

        account = basis["account"]
        adjustment_lines.append(
            {
                "account_id": account_id,
                "name": f"{account.name} market valuation adjustment",
                "type": AccountType.ASSET,
                "parent_id": account.parent_id,
                "amount": adjustment,
                "provenance": "derived",
                "source_currency": _single_source_currency(basis["source_currencies"], target_currency),
                "allocation_asset_class": "public_equity",
                "allocation_liquidity_class": ManualValuationLiquidityClass.LIQUID.value,
                "allocation_source_type": "portfolio_market_adjustment",
            }
        )

    adjustment_lines.sort(key=lambda line: line["name"].lower())
    return adjustment_lines


async def _build_manual_valuation_lines(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    target_currency: str,
    include_restricted: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build balance sheet lines from latest manual valuation components."""
    components = await AssetService().get_latest_valuation_components(
        db,
        user_id,
        as_of_date=as_of_date,
        include_restricted=include_restricted,
    )
    asset_lines: list[dict[str, Any]] = []
    liability_lines: list[dict[str, Any]] = []

    for component in components.items:
        amount = component.value
        source_currency = component.currency.upper()
        if source_currency != target_currency:
            try:
                amount = await convert_amount(
                    db,
                    amount=amount,
                    currency=source_currency,
                    target_currency=target_currency,
                    rate_date=as_of_date,
                    lazy_load=True,
                )
            except FxRateError as exc:
                raise ReportError(str(exc)) from exc

        is_liability = component.liquidity_class == ManualValuationLiquidityClass.LIABILITY.value
        line = {
            "account_id": component.id,
            "name": _valuation_line_name(component.source, component.component_type),
            "type": AccountType.LIABILITY if is_liability else AccountType.ASSET,
            "parent_id": None,
            "amount": _quantize_money(amount),
            # Manual valuations are user-supplied, explicitly trusted data (vision:
            # "manual data is explicitly trusted"), mirroring source_type=manual.
            "confidence_tier": "TRUSTED",
            "provenance": "manual",
            "source_currency": source_currency,
            "allocation_asset_class": _manual_valuation_allocation_asset_class(component.component_type),
            "allocation_liquidity_class": component.liquidity_class,
            "allocation_source_type": "manual_valuation",
        }
        if is_liability:
            liability_lines.append(line)
        else:
            asset_lines.append(line)

    asset_lines.sort(key=lambda line: line["name"].lower())
    liability_lines.sort(key=lambda line: line["name"].lower())
    return asset_lines, liability_lines


async def generate_balance_sheet(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    currency: str | None = None,
    include_restricted: bool = True,
    include_allocation_metadata: bool = False,
    include_trust_signals: bool = True,
) -> dict[str, object]:
    """Generate balance sheet report as of a given date.

    ``include_trust_signals`` gates the two extra per-account ledger scans that
    derive confidence tier and provenance. Callers that do not render per-line
    trust badges (net-worth time series, the income statement's internal balance
    sheets) pass False to avoid amplifying those scans.
    """
    target_currency = _normalize_currency(currency)
    fx_warnings: list[FxWarning] = []
    account_types = (AccountType.ASSET, AccountType.LIABILITY, AccountType.EQUITY)
    accounts = await _load_accounts(db, user_id, account_types)
    included_ledger_currencies: set[str] = set()

    try:
        balances = await _aggregate_balances_sql(
            db,
            user_id,
            account_types,
            target_currency,
            as_of_date,
            fx_warnings=fx_warnings,
            included_currencies=included_ledger_currencies,
        )
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

    tiers: dict[UUID, str] = {}
    provenance_by_account: dict[UUID, DataProvenance | None] = {}
    if include_trust_signals:
        tiers = await _aggregate_account_confidence_tiers(
            db,
            user_id,
            account_types,
            as_of_date,
            included_currencies=included_ledger_currencies,
        )
        provenance_by_account = await _aggregate_account_provenance(
            db,
            user_id,
            account_types,
            as_of_date,
            included_currencies=included_ledger_currencies,
        )

    assets = _build_account_lines(
        accounts,
        balances,
        AccountType.ASSET,
        tiers=tiers,
        provenance_by_account=provenance_by_account,
    )
    liabilities = _build_account_lines(
        accounts,
        balances,
        AccountType.LIABILITY,
        tiers=tiers,
        provenance_by_account=provenance_by_account,
    )
    equity = _build_account_lines(
        accounts,
        balances,
        AccountType.EQUITY,
        tiers=tiers,
        provenance_by_account=provenance_by_account,
    )
    portfolio_adjustments = await _build_portfolio_market_adjustment_lines(
        db,
        user_id,
        as_of_date=as_of_date,
        target_currency=target_currency,
        asset_lines=assets,
    )
    valuation_assets, valuation_liabilities = await _build_manual_valuation_lines(
        db,
        user_id,
        as_of_date=as_of_date,
        target_currency=target_currency,
        include_restricted=include_restricted,
    )
    assets.extend(portfolio_adjustments)
    assets.extend(valuation_assets)
    liabilities.extend(valuation_liabilities)

    total_assets = _line_total(assets)
    total_liabilities = _line_total(liabilities)
    total_equity = _line_total(equity)

    # Calculate cumulative Net Income (Income - Expenses) up to as_of_date
    # Uses period-average FX rates for consistency with the income statement
    try:
        net_income = await _aggregate_net_income_sql(
            db,
            user_id,
            target_currency,
            as_of_date,
            fx_warnings=fx_warnings,
        )
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

    try:
        fx_revaluation = await calculate_unrealized_fx_gains(db, user_id, as_of_date)
        unrealized_fx = _quantize_money(fx_revaluation.total_unrealized_gain_loss)
    except RevaluationError as exc:
        if "Missing FX rate" not in str(exc):
            raise ReportError(str(exc)) from exc
        fx_warnings.append(
            {
                "type": "missing_fx_revaluation_partial_skip",
                "as_of_date": as_of_date.isoformat(),
                "message": str(exc),
            }
        )
        logger.warning(
            "Skipping unrealized FX revaluation because FX rate is unavailable",
            error_id=ErrorIds.REPORT_FX_FALLBACK,
            as_of_date=as_of_date.isoformat(),
            error=str(exc),
        )
        unrealized_fx = Decimal("0.00")
    net_worth_adjustment = _quantize_money(
        _line_total(portfolio_adjustments) + _line_total(valuation_assets) - _line_total(valuation_liabilities)
    )
    total_liab_equity_inc = total_liabilities + total_equity + net_income + unrealized_fx + net_worth_adjustment
    equation_delta = _quantize_money(total_assets - total_liab_equity_inc)

    # Net Worth / balance-sheet aggregate tier: the worst-input tier across every
    # rated line. Lines with no derivable tier (e.g. market-derived adjustments)
    # are excluded rather than counted as trusted.
    aggregate_tier = _worst_confidence_tier(line.get("confidence_tier") for line in (*assets, *liabilities, *equity))
    response_assets = assets if include_allocation_metadata else _strip_allocation_metadata(assets)
    response_liabilities = liabilities if include_allocation_metadata else _strip_allocation_metadata(liabilities)
    response_equity = equity if include_allocation_metadata else _strip_allocation_metadata(equity)

    return {
        "as_of_date": as_of_date,
        "currency": target_currency,
        "assets": response_assets,
        "liabilities": response_liabilities,
        "equity": response_equity,
        "confidence_tier": aggregate_tier,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity,
        "net_income": net_income,
        "unrealized_fx_gain_loss": unrealized_fx,
        "net_worth_adjustment_gain_loss": net_worth_adjustment,
        "fx_warnings": fx_warnings,
        "equation_delta": equation_delta,
        "is_balanced": abs(equation_delta) < Decimal("0.01"),
    }


def _allocation_source_href(
    source_type: str,
    source_id: UUID | None,
    *,
    as_of_date: date,
    currency: str,
) -> str | None:
    if source_type == "ledger_account" and source_id is not None:
        return (
            f"/reports/account-lineage?account_id={source_id}&as_of_date={as_of_date.isoformat()}&currency={currency}"
        )
    if source_type == "manual_valuation":
        return "/assets/valuation-components"
    if source_type == "portfolio_market_adjustment":
        return "/portfolio/holdings"
    return None


def _allocation_source_line(
    line: dict[str, Any],
    *,
    value: Decimal,
    label: str,
    source_type: str,
    as_of_date: date,
    currency: str,
) -> dict[str, Any]:
    source_id = line.get("account_id")
    return {
        "source_type": source_type,
        "source_id": source_id,
        "label": label,
        "value": _quantize_money(value),
        "href": _allocation_source_href(
            source_type,
            source_id if isinstance(source_id, UUID) else None,
            as_of_date=as_of_date,
            currency=currency,
        ),
    }


def _add_allocation_component(
    grouped: dict[tuple[str, str, str], dict[str, Any]],
    *,
    asset_class: str,
    liquidity_class: str,
    source_currency: str,
    value: Decimal,
    source_line: dict[str, Any],
) -> None:
    value = _quantize_money(value)
    if value == Decimal("0.00"):
        return
    key = (asset_class, liquidity_class, source_currency)
    row = grouped.setdefault(
        key,
        {
            "asset_class": asset_class,
            "liquidity_class": liquidity_class,
            "source_currency": source_currency,
            "value": Decimal("0.00"),
            "source_lines": [],
        },
    )
    row["value"] = _quantize_money(Decimal(str(row["value"])) + value)
    row["source_lines"].append(source_line)


def _add_asset_allocation_line(
    grouped: dict[tuple[str, str, str], dict[str, Any]],
    line: dict[str, Any],
    *,
    portfolio_basis_by_account: dict[UUID, dict[str, Any]],
    as_of_date: date,
    currency: str,
) -> None:
    amount = _quantize_money(Decimal(str(line["amount"])))
    source_type = str(line.get("allocation_source_type") or "ledger_account")
    account_id = line.get("account_id")
    basis = portfolio_basis_by_account.get(account_id) if isinstance(account_id, UUID) else None

    if (
        line.get("type") == AccountType.ASSET
        and source_type == "ledger_account"
        and basis is not None
        and amount >= Decimal(str(basis["cost_basis"]))
        and Decimal(str(basis["cost_basis"])) > Decimal("0.00")
    ):
        cost_basis = _quantize_money(Decimal(str(basis["cost_basis"])))
        portfolio_currency = _single_source_currency(basis["source_currencies"], currency)
        _add_allocation_component(
            grouped,
            asset_class="public_equity",
            liquidity_class=ManualValuationLiquidityClass.LIQUID.value,
            source_currency=portfolio_currency,
            value=cost_basis,
            source_line=_allocation_source_line(
                line,
                value=cost_basis,
                label=f"{line['name']} ledger cost basis",
                source_type=source_type,
                as_of_date=as_of_date,
                currency=currency,
            ),
        )
        residual = _quantize_money(amount - cost_basis)
        _add_allocation_component(
            grouped,
            asset_class="cash",
            liquidity_class=ManualValuationLiquidityClass.LIQUID.value,
            source_currency=str(line.get("source_currency") or currency),
            value=residual,
            source_line=_allocation_source_line(
                line,
                value=residual,
                label=f"{line['name']} residual cash",
                source_type=source_type,
                as_of_date=as_of_date,
                currency=currency,
            ),
        )
        return

    _add_allocation_component(
        grouped,
        asset_class=str(line.get("allocation_asset_class") or "other"),
        liquidity_class=str(line.get("allocation_liquidity_class") or ManualValuationLiquidityClass.LIQUID.value),
        source_currency=str(line.get("source_currency") or currency),
        value=amount,
        source_line=_allocation_source_line(
            line,
            value=amount,
            label=str(line["name"]),
            source_type=source_type,
            as_of_date=as_of_date,
            currency=currency,
        ),
    )


def _add_liability_allocation_line(
    grouped: dict[tuple[str, str, str], dict[str, Any]],
    line: dict[str, Any],
    *,
    as_of_date: date,
    currency: str,
) -> None:
    value = -_quantize_money(Decimal(str(line["amount"])))
    source_type = str(line.get("allocation_source_type") or "ledger_account")
    _add_allocation_component(
        grouped,
        asset_class=str(line.get("allocation_asset_class") or "liability"),
        liquidity_class=str(line.get("allocation_liquidity_class") or ManualValuationLiquidityClass.LIABILITY.value),
        source_currency=str(line.get("source_currency") or currency),
        value=value,
        source_line=_allocation_source_line(
            line,
            value=value,
            label=str(line["name"]),
            source_type=source_type,
            as_of_date=as_of_date,
            currency=currency,
        ),
    )


def _allocation_percentage(value: Decimal, net_worth: Decimal) -> Decimal | None:
    if net_worth == Decimal("0.00"):
        return None
    return (value / net_worth * Decimal("100")).quantize(Decimal("0.01"))


async def get_net_worth_allocation_schedule(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    currency: str | None = None,
    include_restricted: bool = True,
) -> dict[str, object]:
    """Return signed net-worth allocation rows grouped by asset/liquidity/currency."""
    target_currency = _normalize_currency(currency)
    balance_sheet = await generate_balance_sheet(
        db,
        user_id,
        as_of_date=as_of_date,
        currency=target_currency,
        include_restricted=include_restricted,
        include_allocation_metadata=True,
    )
    portfolio_basis_by_account = await _portfolio_market_basis_by_account(
        db,
        user_id,
        as_of_date=as_of_date,
        target_currency=target_currency,
    )
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    asset_lines = cast(list[dict[str, Any]], balance_sheet["assets"])
    liability_lines = cast(list[dict[str, Any]], balance_sheet["liabilities"])
    for line in asset_lines:
        _add_asset_allocation_line(
            grouped,
            line,
            portfolio_basis_by_account=portfolio_basis_by_account,
            as_of_date=as_of_date,
            currency=target_currency,
        )
    for line in liability_lines:
        _add_liability_allocation_line(
            grouped,
            line,
            as_of_date=as_of_date,
            currency=target_currency,
        )

    total_assets = _quantize_money(Decimal(str(balance_sheet["total_assets"])))
    total_liabilities = _quantize_money(Decimal(str(balance_sheet["total_liabilities"])))
    net_worth = _quantize_money(total_assets - total_liabilities)
    rows = []
    for row in grouped.values():
        value = _quantize_money(Decimal(str(row["value"])))
        rows.append(
            {
                "asset_class": row["asset_class"],
                "liquidity_class": row["liquidity_class"],
                "source_currency": row["source_currency"],
                "value": value,
                "percentage_of_net_worth": _allocation_percentage(value, net_worth),
                "source_line_count": len(row["source_lines"]),
                "source_lines": row["source_lines"],
            }
        )
    rows.sort(key=lambda row: (row["asset_class"], row["liquidity_class"], row["source_currency"]))

    return {
        "as_of_date": as_of_date,
        "currency": target_currency,
        "include_restricted": include_restricted,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "net_worth": net_worth,
        "rows": rows,
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
    fx_warnings: list[FxWarning] = []

    account_types: tuple[AccountType, ...]
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
    fx_rates = PrefetchedFxRates(fx_warnings, lazy_load=True)
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

    provenance_inputs_by_account: dict[UUID, list[DataProvenance | None]] = {}
    for entry_id, lines_and_accounts in entries_by_id.items():
        if entry_id not in entries_to_include:
            continue

        for line, account, entry in lines_and_accounts:
            provenance_inputs_by_account.setdefault(account.id, []).append(
                _provenance_from_source_type(entry.source_type)
            )
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
                        fx_warnings=fx_warnings,
                        lazy_load=True,
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
                            lazy_load=True,
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

    provenance_by_account = {
        account_id: _combine_provenance(provenance_values)
        for account_id, provenance_values in provenance_inputs_by_account.items()
    }
    income_lines = _build_account_lines(
        accounts,
        balances,
        AccountType.INCOME,
        provenance_by_account=provenance_by_account,
    )
    expense_lines = _build_account_lines(
        accounts,
        balances,
        AccountType.EXPENSE,
        provenance_by_account=provenance_by_account,
    )

    total_income = _quantize_money(sum((Decimal(str(line["amount"])) for line in income_lines), Decimal("0")))
    total_expenses = _quantize_money(sum((Decimal(str(line["amount"])) for line in expense_lines), Decimal("0")))
    net_income = _quantize_money(total_income - total_expenses)

    # Calculate Unrealized FX Gain/Loss for the period
    # This requires balance sheets at both points
    bs_start = await generate_balance_sheet(
        db, user_id, as_of_date=start_date - timedelta(days=1), currency=target_currency, include_trust_signals=False
    )
    bs_end = await generate_balance_sheet(
        db, user_id, as_of_date=end_date, currency=target_currency, include_trust_signals=False
    )

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

    # EPIC-018 Phase 4: Layer 3 classification breakdown
    classification_breakdown: list[dict[str, Any]] = []
    try:
        from src.models.layer2 import AtomicTransaction
        from src.models.layer3 import ClassificationStatus, TransactionClassification

        cls_stmt = (
            select(
                Account.name.label("account_name"),
                Account.type.label("account_type"),
                func.count(TransactionClassification.id).label("count"),
                func.avg(TransactionClassification.confidence_score).label("avg_confidence"),
            )
            .join(Account, TransactionClassification.account_id == Account.id)
            .join(AtomicTransaction, TransactionClassification.atomic_txn_id == AtomicTransaction.id)
            .where(TransactionClassification.status == ClassificationStatus.APPLIED)
            .where(Account.user_id == user_id)
            .where(Account.type.in_(account_types))
            .where(AtomicTransaction.txn_date >= start_date)
            .where(AtomicTransaction.txn_date <= end_date)
            .group_by(Account.name, Account.type)
            .order_by(func.count(TransactionClassification.id).desc())
            .limit(50)
        )
        cls_result = await db.execute(cls_stmt)
        for row in cls_result.all():
            classification_breakdown.append(
                {
                    "account_name": row.account_name,
                    "account_type": row.account_type.value
                    if hasattr(row.account_type, "value")
                    else str(row.account_type),
                    "classified_count": row.count,
                    "avg_confidence": round(float(row.avg_confidence or 0), 1),
                }
            )
    except Exception as e:
        logger.warning(
            "Failed to build classification breakdown, skipping",
            error=str(e),
            error_type=type(e).__name__,
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
        "fx_warnings": fx_warnings,
        "trends": trend_items,
        "classification_breakdown": classification_breakdown,
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

    fx_rates = PrefetchedFxRates(lazy_load=True)
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


async def get_net_worth_timeseries(
    db: AsyncSession,
    user_id: UUID,
    *,
    start_date: date,
    end_date: date,
    granularity: str,
    currency: str | None = None,
) -> dict[str, object]:
    """Get historical net worth points from balance sheet snapshots."""
    if start_date > end_date:
        raise ReportError("from date must be before to date")
    if granularity not in {"daily", "monthly"}:
        raise ReportError(f"Unsupported net worth granularity: {granularity}")

    day_count = (end_date - start_date).days + 1
    if granularity == "daily" and day_count > MAX_NET_WORTH_DAILY_POINTS:
        raise ReportError(f"Daily net worth time-series is capped at {MAX_NET_WORTH_DAILY_POINTS} points")

    target_currency = _normalize_currency(currency)
    spans = _iter_periods(start_date, end_date, granularity)
    points: list[dict[str, object]] = []
    for span in spans:
        point_date = span.start if granularity == "daily" else span.end
        balance_sheet = await generate_balance_sheet(
            db, user_id, as_of_date=point_date, currency=target_currency, include_trust_signals=False
        )
        total_assets = _quantize_money(Decimal(str(balance_sheet["total_assets"])))
        total_liabilities = _quantize_money(Decimal(str(balance_sheet["total_liabilities"])))
        points.append(
            {
                "date": point_date,
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "net_worth": _quantize_money(total_assets - total_liabilities),
                "currency": target_currency,
            }
        )

    return {"currency": target_currency, "granularity": granularity, "points": points}


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

    fx_rates = PrefetchedFxRates(lazy_load=True)
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
    items.sort(key=lambda item: Decimal(str(item["total"])), reverse=True)

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

    agg_stmt_ending = (
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
        .where(JournalEntry.entry_date <= end_date)
        .group_by(Account.id, JournalLine.currency, JournalLine.direction)
    )
    result_ending = await db.execute(agg_stmt_ending)
    rows_ending = result_ending.all()

    fx_needs: list[tuple[str, str, date, date | None, date | None]] = []
    for row in rows_before:
        if row.currency.upper() != target_currency:
            fx_needs.append((row.currency, target_currency, start_date, None, None))
    for row in rows_during:
        if row.currency.upper() != target_currency:
            fx_needs.append((row.currency, target_currency, end_date, None, None))
    for row in rows_ending:
        if row.currency.upper() != target_currency:
            fx_needs.append((row.currency, target_currency, end_date, None, None))

    fx_rates = PrefetchedFxRates(lazy_load=True)
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

    activity_movements: dict[UUID, Decimal] = {}
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
            if row.account_id not in activity_movements:
                activity_movements[row.account_id] = Decimal("0")
            activity_movements[row.account_id] += _signed_amount(account.type, row.direction, converted)

    balances_ending: dict[UUID, Decimal] = {}
    for row in rows_ending:
        rate = fx_rates.get_rate(row.currency, target_currency, end_date)
        if rate is None:
            if row.currency.upper() == target_currency:
                rate = Decimal("1")
            else:
                raise ReportError(f"No FX rate available for {row.currency}/{target_currency} on {end_date}")

        converted = Decimal(str(row.total)) * rate
        account = account_id_to_account.get(row.account_id)
        if account:
            if row.account_id not in balances_ending:
                balances_ending[row.account_id] = Decimal("0")
            balances_ending[row.account_id] += _signed_amount(account.type, row.direction, converted)

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
            ending_cash += balances_ending.get(acc_id, Decimal("0"))

    operating_items: list[dict[str, object]] = []
    investing_items: list[dict[str, object]] = []
    financing_items: list[dict[str, object]] = []

    def cash_flow_amount(account: Account, movement: Decimal) -> Decimal:
        if account.type == AccountType.INCOME:
            return movement
        if account.type == AccountType.EXPENSE:
            return -movement
        if account.type == AccountType.ASSET:
            return -movement
        return movement

    for acc_id, movement in activity_movements.items():
        if movement == Decimal("0"):
            continue
        account = account_id_to_account[acc_id]
        if is_cash_account(account):
            continue
        amount = cash_flow_amount(account, movement)
        item = {
            "category": "",
            "subcategory": account.name,
            "amount": _quantize_money(amount),
            "description": f"{'Inflow' if amount > 0 else 'Outflow'} - {account.name}",
            # EPIC-022 #887: anchor the line to its account for report drill-down.
            "account_id": acc_id,
        }
        if account.type in (AccountType.INCOME, AccountType.EXPENSE):
            item["category"] = "Operating"
            operating_items.append(item)
        elif account.type == AccountType.ASSET:
            item["category"] = "Investing"
            investing_items.append(item)
        else:
            item["category"] = "Financing"
            financing_items.append(item)

    operating_items.sort(key=lambda x: abs(Decimal(str(x["amount"]))), reverse=True)
    investing_items.sort(key=lambda x: abs(Decimal(str(x["amount"]))), reverse=True)
    financing_items.sort(key=lambda x: abs(Decimal(str(x["amount"]))), reverse=True)

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
