"""Shared reporting aggregation core (SQL balances, fx, account lines, net-income)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.config_app import get_effective_base_currency
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalLine,
    account_service,
)
from src.ledger.orm.journal import active_journal_entry_filter
from src.observability import ErrorIds, get_logger
from src.pricing import (
    FxWarning,
    ManualValuationLiquidityClass,
    PrefetchedFxRates,
    PricingError,
    get_average_rate,
    get_exchange_rate,
)
from src.reporting.extension.internal_transfer import _internal_transfer_adjustment
from src.reporting.extension.reporting_calc import (
    ReportError,
    _combine_provenance,
    _provenance_from_source_type,
    _quantize_money,
)
from src.schemas.provenance import DataProvenance

logger = get_logger(__name__)

REPORTING_QUANTITY_UNIT = "units"


def _restate_unrounded(amount: Decimal | int | str, rate: Decimal) -> Decimal:
    """Multiply normalized Decimal amount by rate without intermediate rounding."""
    return Decimal(str(amount)) * rate


async def _prefetch_fx_rates(
    db: AsyncSession,
    fx_needs: Sequence[tuple[str, str, date, date | None, date | None]],
    context_label: str,
    *,
    fx_warnings: list[FxWarning] | None = None,
    prefetched_cls: Any = PrefetchedFxRates,
    **log_extra: Any,
) -> PrefetchedFxRates:
    """Batch-prefetch FX rates for reporting queries and translate PricingError to ReportError."""
    fx_rates: PrefetchedFxRates = prefetched_cls(fx_warnings, lazy_load=True)
    if fx_needs:
        try:
            await fx_rates.prefetch(db, list(fx_needs))
        except PricingError as exc:
            logger.error(
                f"FX pre-fetch failed for {context_label}",
                error_id=ErrorIds.REPORT_GENERATION_FAILED,
                error=str(exc),
                **log_extra,
            )
            raise ReportError(str(exc)) from exc
    return fx_rates


def _base_ledger_lines_filter(
    stmt: Any,
    user_id: UUID,
    account_types: Sequence[AccountType],
    as_of_date: date,
    *,
    start_date: date | None = None,
    excluded_entry_ids: set[UUID] | frozenset[UUID] | None = None,
) -> Any:
    """Apply canonical reporting joins and active non-revaluation filters to a JournalLine/Account select."""
    stmt = (
        stmt.join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(
            Account.user_id == user_id,
            Account.type.in_(account_types),
            JournalEntry.user_id == user_id,
            active_journal_entry_filter(JournalEntry),
            JournalEntry.source_type != JournalEntrySourceType.FX_REVALUATION,
            JournalEntry.entry_date <= as_of_date,
        )
    )
    if excluded_entry_ids:
        stmt = stmt.where(JournalEntry.id.not_in(excluded_entry_ids))
    if start_date:
        stmt = stmt.where(JournalEntry.entry_date >= start_date)
    return stmt


def _build_account_lines(
    accounts: Sequence[Account],
    balances: dict[UUID, Decimal],
    filter_type: AccountType,
    provenance_by_account: dict[UUID, DataProvenance | None] | None = None,
    native_balances: dict[UUID, Decimal] | None = None,
) -> list[dict[str, Any]]:
    items = sorted(
        (
            account
            for account in accounts
            if account.type == filter_type
            and not (
                account.is_system
                and account.code == account_service.UNEXPLAINED_GAP_EQUITY_CODE
                and _quantize_money(balances.get(account.id, Decimal("0"))) == Decimal("0.00")
            )
        ),
        key=lambda acc: acc.name.lower(),
    )
    return [
        {
            "account_id": account.id,
            "name": account.name,
            "type": account.type,
            "parent_id": account.parent_id,
            "amount": _quantize_money(balances.get(account.id, Decimal("0"))),
            "provenance": provenance_by_account.get(account.id) if provenance_by_account is not None else None,
            "source_currency": account.currency.upper(),
            **(
                {"native_amount": _quantize_money(native_balances.get(account.id, Decimal("0")))}
                if native_balances is not None
                else {}
            ),
            "allocation_asset_class": _ledger_allocation_asset_class(account),
            "allocation_liquidity_class": _ledger_allocation_liquidity_class(account),
            "allocation_source_type": "ledger_account",
        }
        for account in items
    ]


def _line_total(lines: Sequence[dict[str, Any]]) -> Decimal:
    return _quantize_money(sum((Decimal(str(line["amount"])) for line in lines), Decimal("0")))


def _ledger_allocation_asset_class(account: Account) -> str:
    if account.type == AccountType.LIABILITY:
        return "liability"
    return "cash" if account.type == AccountType.ASSET else "other"


def _ledger_allocation_liquidity_class(account: Account) -> str:
    return (
        ManualValuationLiquidityClass.LIABILITY.value
        if account.type == AccountType.LIABILITY
        else ManualValuationLiquidityClass.LIQUID.value
    )


def _single_source_currency(source_currencies: set[str], target_currency: str) -> str:
    return next(iter(source_currencies)) if len(source_currencies) == 1 else target_currency


async def _load_accounts(
    db: AsyncSession, user_id: UUID, account_types: tuple[AccountType, ...] | None = None
) -> list[Account]:
    stmt = select(Account).where(Account.user_id == user_id)
    if account_types is not None:
        stmt = stmt.where(Account.type.in_(account_types))
    return list((await db.execute(stmt)).scalars().all())


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
        except PricingError as exc:
            warning: FxWarning = {
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


async def _distinct_ledger_currencies(
    db: AsyncSession,
    user_id: UUID,
    account_types: Sequence[AccountType],
    as_of_date: date,
    *,
    start_date: date | None = None,
    excluded_entry_ids: set[UUID] | frozenset[UUID] | None = None,
) -> set[str]:
    stmt = _base_ledger_lines_filter(
        select(JournalLine.currency).distinct().join(Account, JournalLine.account_id == Account.id),
        user_id,
        account_types,
        as_of_date,
        start_date=start_date,
        excluded_entry_ids=excluded_entry_ids,
    )
    return {row[0].upper() for row in (await db.execute(stmt)).all() if row[0]}


async def _aggregate_balances_sql(
    db: AsyncSession,
    user_id: UUID,
    account_types: tuple[AccountType, ...],
    target_currency: str,
    as_of_date: date,
    *,
    start_date: date | None = None,
    base_currency: str | None = None,
    fx_warnings: list[FxWarning] | None = None,
    included_currencies: set[str] | None = None,
    native_balances: dict[UUID, Decimal] | None = None,
) -> dict[UUID, Decimal]:
    """Aggregate account balances using SQL SUM/GROUP BY with FX conversion."""
    currencies = await _distinct_ledger_currencies(db, user_id, account_types, as_of_date, start_date=start_date)
    if not currencies:
        return {}

    fx_rates = await _get_fx_rates_map(db, currencies, target_currency, as_of_date, fx_warnings=fx_warnings)
    if not fx_rates and native_balances is None:
        return {}
    if included_currencies is not None:
        included_currencies.update(fx_rates.keys())

    fx_case_parts: list[tuple[Any, Any]] = []
    if AccountType.EQUITY in account_types and fx_rates:
        effective_base = (base_currency or await get_effective_base_currency(db, user_id=user_id)).upper()
        fx_case_parts.append(
            (
                (Account.type == AccountType.EQUITY)
                & JournalLine.currency.in_(list(fx_rates.keys()))
                & (func.upper(JournalLine.currency) != target_currency.upper())
                & (
                    func.upper(func.coalesce(JournalEntry.base_currency, literal(effective_base)))
                    == target_currency.upper()
                )
                & JournalLine.fx_rate.is_not(None),
                JournalLine.fx_rate,
            )
        )
    fx_case_parts.extend((JournalLine.currency == currency, literal(rate)) for currency, rate in fx_rates.items())
    fx_rate_expr = case(*fx_case_parts, else_=literal(Decimal("0"))) if fx_case_parts else literal(Decimal("0"))

    debit_normal = Account.type.in_((AccountType.ASSET, AccountType.EXPENSE))
    credit_normal = Account.type.in_((AccountType.LIABILITY, AccountType.EQUITY, AccountType.INCOME))
    sign_expr = case(
        (debit_normal & (JournalLine.direction == Direction.DEBIT), literal(1)),
        (debit_normal & (JournalLine.direction == Direction.CREDIT), literal(-1)),
        (credit_normal & (JournalLine.direction == Direction.CREDIT), literal(1)),
        (credit_normal & (JournalLine.direction == Direction.DEBIT), literal(-1)),
        else_=literal(1),
    )
    native_expr = case(
        (func.upper(JournalLine.currency) == func.upper(Account.currency), JournalLine.amount * sign_expr),
        else_=literal(Decimal("0")),
    )

    agg_stmt = _base_ledger_lines_filter(
        select(
            Account.id.label("account_id"),
            func.sum(JournalLine.amount * fx_rate_expr * sign_expr).label("balance"),
            func.sum(native_expr).label("native_balance"),
        ).join(Account, JournalLine.account_id == Account.id),
        user_id,
        account_types,
        as_of_date,
        start_date=start_date,
    ).group_by(Account.id)
    if native_balances is None:
        agg_stmt = agg_stmt.where(JournalLine.currency.in_(list(fx_rates.keys())))

    rows = (await db.execute(agg_stmt)).all()
    if native_balances is not None:
        for row in rows:
            native_balances[row.account_id] = Decimal(str(row.native_balance)) if row.native_balance else Decimal("0")
    if not fx_rates:
        return {}
    return {row.account_id: Decimal(str(row.balance)) if row.balance else Decimal("0") for row in rows}


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

    stmt = _base_ledger_lines_filter(
        select(Account.id.label("account_id"), JournalEntry.source_type)
        .distinct()
        .join(JournalLine, JournalLine.account_id == Account.id),
        user_id,
        account_types,
        as_of_date,
        start_date=start_date,
    )
    if included_currencies is not None:
        stmt = stmt.where(JournalLine.currency.in_(list(included_currencies)))

    provenance_inputs: dict[UUID, list[DataProvenance | None]] = {}
    for row in (await db.execute(stmt)).all():
        provenance_inputs.setdefault(row.account_id, []).append(_provenance_from_source_type(row.source_type))
    return {account_id: _combine_provenance(vals) for account_id, vals in provenance_inputs.items()}


async def _aggregate_net_income_sql(
    db: AsyncSession,
    user_id: UUID,
    target_currency: str,
    as_of_date: date,
    *,
    start_date: date | None = None,
    fx_warnings: list[FxWarning] | None = None,
) -> tuple[Decimal, Decimal]:
    """Aggregate net income and spot-vs-average translation variance using period-average FX rates."""
    transfer_adjustment = await _internal_transfer_adjustment(
        db, user_id, target_currency, as_of_date, start_date=start_date
    )
    excluded_entry_ids = transfer_adjustment.excluded_entry_ids
    pnl_types = (AccountType.INCOME, AccountType.EXPENSE)

    currencies = await _distinct_ledger_currencies(
        db, user_id, pnl_types, as_of_date, start_date=start_date, excluded_entry_ids=excluded_entry_ids
    )
    if not currencies:
        return Decimal("0"), Decimal("0")

    effective_start = start_date if start_date is not None else date.min
    fx_rate_map: dict[str, Decimal] = {}
    for source in currencies:
        if source == target_currency:
            fx_rate_map[source] = Decimal("1")
            continue
        try:
            fx_rate_map[source] = await get_average_rate(
                db, source, target_currency, effective_start, as_of_date, fx_warnings=fx_warnings, lazy_load=True
            )
        except PricingError as exc:
            raise ReportError(str(exc)) from exc

    spot_rate_map = await _get_fx_rates_map(db, currencies, target_currency, as_of_date, fx_warnings=fx_warnings)
    agg_stmt = _base_ledger_lines_filter(
        select(
            JournalLine.currency,
            Account.type,
            JournalLine.direction,
            func.sum(JournalLine.amount).label("total"),
        ).join(Account, JournalLine.account_id == Account.id),
        user_id,
        pnl_types,
        as_of_date,
        start_date=start_date,
        excluded_entry_ids=excluded_entry_ids,
    ).group_by(JournalLine.currency, Account.type, JournalLine.direction)

    net_income = Decimal("0")
    net_income_spot = Decimal("0")
    for row in (await db.execute(agg_stmt)).all():
        currency_upper = row.currency.upper()
        fx_rate = fx_rate_map.get(currency_upper)
        if fx_rate is None:
            raise ReportError(f"Missing FX rate for {currency_upper}/{target_currency} - data consistency error")
        sign = Decimal("1") if row.direction == Direction.CREDIT else Decimal("-1")
        net_income += sign * _restate_unrounded(row.total, fx_rate)
        net_income_spot += sign * _restate_unrounded(row.total, spot_rate_map.get(currency_upper, Decimal("1")))

    net_income -= transfer_adjustment.fee_total
    net_income_spot -= transfer_adjustment.fee_total
    return net_income, net_income_spot - net_income


async def _aggregate_equity_translation_variance_sql(
    db: AsyncSession,
    user_id: UUID,
    target_currency: str,
    as_of_date: date,
    *,
    base_currency: str | None = None,
    fx_warnings: list[FxWarning] | None = None,
) -> Decimal:
    """Compute translation variance on equity contributions and non-P&L foreign-currency lines (#2664)."""
    target = target_currency.upper()
    effective_base = (base_currency or await get_effective_base_currency(db, user_id=user_id)).upper()
    equity_entries_stmt = _base_ledger_lines_filter(
        select(JournalLine.journal_entry_id).distinct().join(Account, JournalLine.account_id == Account.id),
        user_id,
        (AccountType.EQUITY,),
        as_of_date,
    )
    equity_entry_ids = {row[0] for row in (await db.execute(equity_entries_stmt)).all()}
    pnl_entries_subq = (
        select(JournalLine.journal_entry_id)
        .join(Account, JournalLine.account_id == Account.id)
        .where(Account.user_id == user_id, Account.type.in_((AccountType.INCOME, AccountType.EXPENSE)))
    )

    stmt = _base_ledger_lines_filter(
        select(
            JournalLine.journal_entry_id,
            JournalLine.direction,
            JournalLine.amount,
            JournalLine.currency,
            JournalLine.fx_rate,
            JournalEntry.entry_date,
            JournalEntry.base_currency,
            Account.type,
            Account.currency.label("account_currency"),
        ).join(Account, JournalLine.account_id == Account.id),
        user_id,
        (AccountType.ASSET, AccountType.LIABILITY),
        as_of_date,
    ).where(JournalEntry.id.not_in(pnl_entries_subq), JournalLine.currency != target)

    rows = [
        row
        for row in (await db.execute(stmt)).all()
        if row.journal_entry_id in equity_entry_ids
        or not (row.account_currency.upper() != effective_base and row.currency.upper() == row.account_currency.upper())
    ]
    if not rows:
        return Decimal("0.00")

    spot_rates = await _get_fx_rates_map(db, {row.currency.upper() for row in rows}, target, as_of_date, fx_warnings=fx_warnings)
    total_variance = Decimal("0.00")
    for row in rows:
        curr = row.currency.upper()
        spot_rate = spot_rates.get(curr)
        if spot_rate is None:
            continue
        entry_base = (getattr(row, "base_currency", None) or effective_base).upper()
        if row.fx_rate is not None and target == entry_base:
            hist_rate = Decimal(str(row.fx_rate))
        else:
            try:
                hist_rate = await get_exchange_rate(db, curr, target, row.entry_date, lazy_load=False)
            except PricingError:
                hist_rate = spot_rate

        sign = (
            (Decimal("1") if row.direction == Direction.DEBIT else Decimal("-1"))
            if row.type == AccountType.ASSET
            else (Decimal("-1") if row.direction == Direction.CREDIT else Decimal("1"))
        )
        total_variance += sign * Decimal(str(row.amount)) * (spot_rate - hist_rate)

    return _quantize_money(total_variance)
