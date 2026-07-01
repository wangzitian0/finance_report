"""Shared reporting aggregation core (SQL balances, fx, account lines, net-income)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money.adopt import restate_unrounded
from src.constants.error_ids import ErrorIds
from src.logger import get_logger
from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.models.layer3 import (
    ManualValuationLiquidityClass,
)
from src.schemas.provenance import DataProvenance
from src.services.confidence_tier import derive_confidence_tier
from src.services.fx import (
    FxRateError,
    FxWarning,
    get_average_rate,
    get_exchange_rate,
)
from src.services.reporting.internal_transfer import _internal_transfer_adjustment
from src.services.reporting_calc import (
    ReportError,
    _combine_provenance,
    _provenance_from_source_type,
    _quantize_money,
    _worst_confidence_tier,
)

logger = get_logger(__name__)

_REPORT_STATUSES = (JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED)
REPORTING_QUANTITY_UNIT = "units"
_ALLOCATION_METADATA_KEYS = {
    "source_currency",
    "allocation_asset_class",
    "allocation_liquidity_class",
    "allocation_source_type",
}


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
    available historical FX rates up to as_of_date (sentinel: ``date.min``).
    If no FX rates exist in the range, get_average_rate falls back to the most recent
    spot rate on or before as_of_date; if that is also absent, FxRateError is raised
    and re-raised here as ReportError.
    """
    # Resolve matched internal (own-account) transfers (#1123 AC3): their legs
    # must NOT double-count as income/expense; only the fee affects net income.
    transfer_adjustment = await _internal_transfer_adjustment(
        db, user_id, target_currency, as_of_date, start_date=start_date
    )
    excluded_entry_ids = transfer_adjustment.excluded_entry_ids

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
    if excluded_entry_ids:
        currency_stmt = currency_stmt.where(JournalEntry.id.not_in(excluded_entry_ids))
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
    if excluded_entry_ids:
        agg_stmt = agg_stmt.where(JournalEntry.id.not_in(excluded_entry_ids))
    if start_date:
        agg_stmt = agg_stmt.where(JournalEntry.entry_date >= start_date)

    result = await db.execute(agg_stmt)

    net_income = Decimal("0")
    for row in result.all():
        currency_upper = row.currency.upper()
        fx_rate = fx_rate_map.get(currency_upper)
        if fx_rate is None:
            raise ReportError(f"Missing FX rate for {currency_upper}/{target_currency} - data consistency error")
        converted = restate_unrounded(row.total, currency_upper, fx_rate, target_currency)
        # Net income sign convention: both income and expense types are credit-normal.
        # - Income CREDIT = +, Income DEBIT = -
        # - Expense DEBIT = - (expenses reduce net income), Expense CREDIT = +
        # Do NOT use _signed_amount here: it returns +amount for EXPENSE DEBIT (account-balance
        # convention), which is the opposite of what the net-income formula needs.
        signed = converted if row.direction == Direction.CREDIT else -converted
        net_income += signed

    # A matched internal transfer's only net-income impact is its fee, which lowers
    # net income like an expense (#1123 AC3). The transfer legs themselves were
    # excluded above, so add the fee back here as the sole net-worth effect.
    net_income -= transfer_adjustment.fee_total

    return net_income
