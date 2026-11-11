"""Net-worth allocation, trends, timeseries, and category breakdown."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.audit.ratio import Ratio
from src.config_app import get_effective_base_currency
from src.ledger import Account, AccountType, JournalEntry, JournalLine
from src.ledger.orm.journal import active_journal_entry_filter
from src.pricing import ManualValuationLiquidityClass, PrefetchedFxRates, PricingError, get_exchange_rate_series
from src.reporting.base.types import DEFAULT_INCLUDE_RESTRICTED
from src.reporting.extension._core import _load_accounts, _prefetch_fx_rates, _single_source_currency
from src.reporting.extension.balance_sheet import _build_manual_valuation_lines_series, generate_balance_sheet
from src.reporting.extension.portfolio_market import (
    _held_on,
    _load_portfolio_positions,
    _portfolio_basis_for_positions,
    _portfolio_eval_date,
    _portfolio_market_adjustment_lines_from_basis,
    _portfolio_market_basis_by_account,
)
from src.reporting.extension.reporting_calc import (
    MAX_NET_WORTH_DAILY_POINTS,
    MAX_NET_WORTH_MONTHLY_POINTS,
    ReportError,
    _add_months,
    _iter_periods,
    _month_start,
    _normalize_currency,
    _quantize_money,
    _quarter_start,
    _signed_amount,
)


def _allocation_source_line(
    line: dict[str, Any],
    *,
    value: Decimal,
    label: str,
    source_type: str,
) -> dict[str, Any]:
    """Return one contributor of an allocation row without route links (#2645)."""
    return {
        "source_type": source_type,
        "source_id": line.get("account_id"),
        "label": label,
        "value": _quantize_money(value),
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
    row = grouped.setdefault(
        (asset_class, liquidity_class, source_currency),
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


def _add_line_component(
    grouped: dict[tuple[str, str, str], dict[str, Any]],
    line: dict[str, Any],
    *,
    value: Decimal,
    default_asset_class: str,
    default_liquidity: str,
    currency: str,
) -> None:
    source_type = str(line.get("allocation_source_type") or "ledger_account")
    _add_allocation_component(
        grouped,
        asset_class=str(line.get("allocation_asset_class") or default_asset_class),
        liquidity_class=str(line.get("allocation_liquidity_class") or default_liquidity),
        source_currency=str(line.get("source_currency") or currency),
        value=value,
        source_line=_allocation_source_line(line, value=value, label=str(line["name"]), source_type=source_type),
    )


def _add_asset_allocation_line(
    grouped: dict[tuple[str, str, str], dict[str, Any]],
    line: dict[str, Any],
    *,
    portfolio_basis_by_account: dict[UUID, dict[str, Any]],
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
        _add_allocation_component(
            grouped,
            asset_class="public_equity",
            liquidity_class=ManualValuationLiquidityClass.LIQUID.value,
            source_currency=_single_source_currency(basis["source_currencies"], currency),
            value=cost_basis,
            source_line=_allocation_source_line(
                line, value=cost_basis, label=f"{line['name']} ledger cost basis", source_type=source_type
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
                line, value=residual, label=f"{line['name']} residual cash", source_type=source_type
            ),
        )
        return

    _add_line_component(
        grouped,
        line,
        value=amount,
        default_asset_class="other",
        default_liquidity=ManualValuationLiquidityClass.LIQUID.value,
        currency=currency,
    )


def _add_liability_allocation_line(
    grouped: dict[tuple[str, str, str], dict[str, Any]],
    line: dict[str, Any],
    *,
    currency: str,
) -> None:
    _add_line_component(
        grouped,
        line,
        value=-_quantize_money(Decimal(str(line["amount"]))),
        default_asset_class="liability",
        default_liquidity=ManualValuationLiquidityClass.LIABILITY.value,
        currency=currency,
    )


def _allocation_percentage(value: Decimal, net_worth: Decimal) -> Decimal | None:
    return None if net_worth == Decimal("0.00") else Ratio.fraction(value, net_worth).to_percent()


async def get_net_worth_allocation_schedule(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date,
    currency: str | None = None,
    include_restricted: bool = DEFAULT_INCLUDE_RESTRICTED,
) -> dict[str, object]:
    """Return signed net-worth allocation rows grouped by asset/liquidity/currency."""
    target_currency = _normalize_currency(currency or await get_effective_base_currency(db, user_id=user_id))
    balance_sheet = await generate_balance_sheet(
        db,
        user_id,
        as_of_date=as_of_date,
        currency=target_currency,
        include_restricted=include_restricted,
    )
    portfolio_basis_by_account = await _portfolio_market_basis_by_account(
        db, user_id, as_of_date=as_of_date, target_currency=target_currency
    )
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for line in cast(list[dict[str, Any]], balance_sheet["assets"]):
        _add_asset_allocation_line(
            grouped, line, portfolio_basis_by_account=portfolio_basis_by_account, currency=target_currency
        )
    for line in cast(list[dict[str, Any]], balance_sheet["liabilities"]):
        _add_liability_allocation_line(grouped, line, currency=target_currency)

    total_assets = _quantize_money(Decimal(str(balance_sheet["total_assets"])))
    total_liabilities = _quantize_money(Decimal(str(balance_sheet["total_liabilities"])))
    net_worth = _quantize_money(total_assets - total_liabilities)
    rows = sorted(
        (
            {
                "asset_class": row["asset_class"],
                "liquidity_class": row["liquidity_class"],
                "source_currency": row["source_currency"],
                "value": (val := _quantize_money(Decimal(str(row["value"])))),
                "percentage_of_net_worth": _allocation_percentage(val, net_worth),
                "source_line_count": len(row["source_lines"]),
                "source_lines": row["source_lines"],
            }
            for row in grouped.values()
        ),
        key=lambda row: (row["asset_class"], row["liquidity_class"], row["source_currency"]),
    )

    return {
        "as_of_date": as_of_date,
        "currency": target_currency,
        "include_restricted": include_restricted,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "net_worth": net_worth,
        "rows": rows,
        "opening_balance_warnings": balance_sheet.get("opening_balance_warnings", []),
        "portfolio_warnings": balance_sheet.get("portfolio_warnings", []),
        "excluded_holdings": balance_sheet["excluded_holdings"],
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
    target_currency = _normalize_currency(currency or await get_effective_base_currency(db, user_id=user_id))
    account = (
        await db.execute(select(Account).where(Account.id == account_id, Account.user_id == user_id))
    ).scalar_one_or_none()
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
        .where(
            JournalLine.account_id == account_id,
            active_journal_entry_filter(JournalEntry),
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= today,
        )
        .group_by(JournalLine.currency, JournalEntry.entry_date, JournalLine.direction)
    )
    rows = (await db.execute(agg_stmt)).all()
    fx_needs = [
        (row.currency, target_currency, row.entry_date, None, None)
        for row in rows
        if row.currency.upper() != target_currency
    ]
    fx_rates = await _prefetch_fx_rates(
        db, fx_needs, "account trend", prefetched_cls=PrefetchedFxRates, account_id=str(account.id)
    )

    spans = _iter_periods(start_date, today, period)
    totals: dict[date, Decimal] = {span.start: Decimal("0") for span in spans}

    for row in rows:
        rate = fx_rates.get_rate(row.currency, target_currency, row.entry_date)
        if rate is None:
            if row.currency.upper() != target_currency:
                raise ReportError(f"No FX rate available for {row.currency}/{target_currency} on {row.entry_date}")
            rate = Decimal("1")

        signed = _signed_amount(account.type, row.direction, Decimal(str(row.total)) * rate)
        key = (
            row.entry_date
            if period == "daily"
            else row.entry_date - timedelta(days=row.entry_date.weekday())
            if period == "weekly"
            else _month_start(row.entry_date)
        )
        totals[key] = totals.get(key, Decimal("0")) + signed

    return {
        "account_id": account_id,
        "currency": target_currency,
        "period": period,
        "points": [
            {
                "period_start": span.start,
                "period_end": span.end,
                "amount": _quantize_money(totals.get(span.start, Decimal("0"))),
            }
            for span in spans
        ],
    }


async def _ledger_net_worth_balances(
    db: AsyncSession,
    user_id: UUID,
    point_dates: list[date],
    target_currency: str,
    *,
    liability_names: dict[UUID, str] | None = None,
) -> list[tuple[dict[UUID, Decimal], dict[UUID, Decimal]]]:
    """Return asset and liability ledger balances by account for each point date."""
    first_point = point_dates[0]
    signed_columns = (JournalLine.account_id, Account.type, Account.name, JournalLine.currency, JournalLine.direction)

    def movement_query(*extra_columns: Any) -> Any:
        return (
            select(*signed_columns, *extra_columns, func.sum(JournalLine.amount).label("total"))
            .join(Account, JournalLine.account_id == Account.id)
            .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
            .where(
                Account.user_id == user_id,
                Account.type.in_((AccountType.ASSET, AccountType.LIABILITY)),
                JournalEntry.user_id == user_id,
                active_journal_entry_filter(JournalEntry),
                JournalEntry.source_type != JournalEntrySourceType.FX_REVALUATION,
            )
            .group_by(*signed_columns, *extra_columns)
        )

    opening_rows = (await db.execute(movement_query().where(JournalEntry.entry_date < first_point))).all()
    daily_rows = (
        await db.execute(
            movement_query(JournalEntry.entry_date).where(
                JournalEntry.entry_date >= first_point,
                JournalEntry.entry_date <= point_dates[-1],
            )
        )
    ).all()

    account_types: dict[UUID, AccountType] = {}
    running: dict[tuple[UUID, str], Decimal] = {}

    def apply(row: Any) -> None:
        account_types[row.account_id] = row.type
        if liability_names is not None and row.type == AccountType.LIABILITY:
            liability_names[row.account_id] = row.name
        key = (row.account_id, row.currency)
        running[key] = running.get(key, Decimal("0")) + _signed_amount(row.type, row.direction, row.total)

    first_seen: dict[str, date] = {}
    for row in opening_rows:
        first_seen.setdefault(row.currency.upper(), first_point)
        apply(row)
    movements_by_date: dict[date, list[Any]] = {}
    for row in daily_rows:
        currency_code = row.currency.upper()
        first_seen[currency_code] = min(first_seen.get(currency_code, row.entry_date), row.entry_date)
        movements_by_date.setdefault(row.entry_date, []).append(row)

    rates_by_currency: dict[str, dict[date, Decimal]] = {}
    for currency_code, seen_on in first_seen.items():
        if currency_code == target_currency.upper():
            continue
        try:
            rates_by_currency[currency_code] = await get_exchange_rate_series(
                db, currency_code, target_currency, [p for p in point_dates if p >= seen_on], lazy_load=True
            )
        except PricingError:
            rates_by_currency[currency_code] = {}

    balances: list[tuple[dict[UUID, Decimal], dict[UUID, Decimal]]] = []
    movement_dates = sorted(movements_by_date)
    next_movement = 0
    for point in point_dates:
        while next_movement < len(movement_dates) and movement_dates[next_movement] <= point:
            for row in movements_by_date[movement_dates[next_movement]]:
                apply(row)
            next_movement += 1
        unrounded: dict[UUID, Decimal] = {}
        for (account_id, line_currency), amount in running.items():
            rate = (
                Decimal("1")
                if line_currency == target_currency.upper()
                else rates_by_currency.get(line_currency, {}).get(point)
            )
            if rate is not None:
                unrounded[account_id] = unrounded.get(account_id, Decimal("0")) + amount * rate
        balances.append(
            (
                {aid: _quantize_money(amt) for aid, amt in unrounded.items() if account_types[aid] == AccountType.ASSET},
                {
                    aid: _quantize_money(amt)
                    for aid, amt in unrounded.items()
                    if account_types[aid] == AccountType.LIABILITY
                },
            )
        )
    return balances


async def _portfolio_adjustment_totals(
    db: AsyncSession,
    user_id: UUID,
    point_dates: list[date],
    ledger_assets: list[dict[UUID, Decimal]],
    target_currency: str,
) -> list[Decimal]:
    """Return portfolio market-value adjustment total for each point date."""
    positions = await _load_portfolio_positions(db, user_id)
    if not positions:
        return [Decimal("0")] * len(point_dates)
    totals: list[Decimal] = []
    for point, assets in zip(point_dates, ledger_assets, strict=True):
        eval_date = await _portfolio_eval_date(db, user_id, point)
        held = [(position, account) for position, account in positions if _held_on(position, eval_date)]
        if not held:
            totals.append(Decimal("0"))
            continue
        basis = await _portfolio_basis_for_positions(
            db, user_id, held, eval_date=eval_date, target_currency=target_currency
        )
        asset_lines = [{"account_id": account_id, "amount": amount} for account_id, amount in assets.items()]
        lines = _portfolio_market_adjustment_lines_from_basis(
            basis, asset_lines=asset_lines, target_currency=target_currency
        )
        totals.append(sum((Decimal(str(line["amount"])) for line in lines), Decimal("0")))
    return totals


def _monthly_series_start(start_date: date, end_date: date) -> date:
    """Move a monthly series start forward so the series keeps the latest months within the cap."""
    month_count = (end_date.year - start_date.year) * 12 + end_date.month - start_date.month + 1
    if month_count <= MAX_NET_WORTH_MONTHLY_POINTS:
        return start_date
    return _add_months(_month_start(end_date), -(MAX_NET_WORTH_MONTHLY_POINTS - 1))


async def get_net_worth_timeseries(
    db: AsyncSession,
    user_id: UUID,
    *,
    start_date: date,
    end_date: date,
    granularity: str,
    currency: str | None = None,
    include_restricted: bool = DEFAULT_INCLUDE_RESTRICTED,
) -> dict[str, object]:
    """Return historical net worth points aligned with balance-sheet valuation rules."""
    if start_date > end_date:
        raise ReportError("from date must be before to date")
    if granularity not in {"daily", "monthly"}:
        raise ReportError(f"Unsupported net worth granularity: {granularity}")

    day_count = (end_date - start_date).days + 1
    if granularity == "daily" and day_count > MAX_NET_WORTH_DAILY_POINTS:
        raise ReportError(f"Daily net worth time-series is capped at {MAX_NET_WORTH_DAILY_POINTS} points")
    if granularity == "monthly":
        start_date = _monthly_series_start(start_date, end_date)

    target_currency = _normalize_currency(currency or await get_effective_base_currency(db, user_id=user_id))
    spans = _iter_periods(start_date, end_date, granularity)
    point_dates = [span.start if granularity == "daily" else span.end for span in spans]

    ledger_liability_names: dict[UUID, str] = {}
    with localcontext() as context:
        context.prec = 60
        ledger = await _ledger_net_worth_balances(
            db, user_id, point_dates, target_currency, liability_names=ledger_liability_names
        )
    ledger_assets = [assets for assets, _ in ledger]
    portfolio_totals = await _portfolio_adjustment_totals(db, user_id, point_dates, ledger_assets, target_currency)
    excluded_ledger_ids_by_date: dict[date, set[UUID]] = {}
    try:
        valuation_lines = await _build_manual_valuation_lines_series(
            db,
            user_id,
            as_of_dates=point_dates,
            target_currency=target_currency,
            include_restricted=include_restricted,
            ledger_liability_names=ledger_liability_names,
            excluded_ledger_ids_by_date=excluded_ledger_ids_by_date,
        )
    except PricingError as exc:
        raise ReportError(str(exc)) from exc

    points: list[dict[str, object]] = []
    for point_date, (assets, liabilities), portfolio_total in zip(point_dates, ledger, portfolio_totals, strict=True):
        valuation_assets, valuation_liabilities = valuation_lines[point_date]
        excluded_ids = excluded_ledger_ids_by_date.get(point_date, set())
        total_assets = _quantize_money(
            sum(assets.values(), Decimal("0"))
            + portfolio_total
            + sum((Decimal(str(line["amount"])) for line in valuation_assets), Decimal("0"))
        )
        total_liabilities = _quantize_money(
            sum((amt for acc_id, amt in liabilities.items() if acc_id not in excluded_ids), Decimal("0"))
            + sum((Decimal(str(line["amount"])) for line in valuation_liabilities), Decimal("0"))
        )
        points.append(
            {
                "date": point_date,
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "net_worth": _quantize_money(total_assets - total_liabilities),
                "currency": target_currency,
            }
        )

    if granularity == "monthly":
        first_with_value = next(
            (
                index
                for index, point in enumerate(points)
                if point["total_assets"] != Decimal("0.00") or point["total_liabilities"] != Decimal("0.00")
            ),
            len(points) - 1,
        )
        points = points[first_with_value:]

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
    target_currency = _normalize_currency(currency or await get_effective_base_currency(db, user_id=user_id))
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
        .where(
            Account.user_id == user_id,
            Account.type == breakdown_type,
            JournalEntry.user_id == user_id,
            active_journal_entry_filter(JournalEntry),
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= today,
        )
        .group_by(Account.id, JournalLine.currency, JournalLine.direction)
    )
    rows = (await db.execute(agg_stmt)).all()
    fx_needs = [
        (row.currency, target_currency, today, start_date, today)
        for row in rows
        if row.currency.upper() != target_currency
    ]
    fx_rates = await _prefetch_fx_rates(db, fx_needs, "category breakdown", prefetched_cls=PrefetchedFxRates)

    for row in rows:
        rate = fx_rates.get_rate(row.currency, target_currency, today, start_date, today)
        if rate is None:
            if row.currency.upper() != target_currency:
                raise ReportError(f"No FX rate available for {row.currency}/{target_currency}")
            rate = Decimal("1")

        if account := account_map.get(row.account_id):
            balances[row.account_id] += _signed_amount(account.type, row.direction, Decimal(str(row.total)) * rate)

    items = sorted(
        (
            {"category_id": account.id, "category_name": account.name, "total": total}
            for account in accounts
            if (total := _quantize_money(balances.get(account.id, Decimal("0")))) != Decimal("0.00")
        ),
        key=lambda item: Decimal(str(item["total"])),
        reverse=True,
    )
    return {
        "type": breakdown_type,
        "currency": target_currency,
        "period_start": start_date,
        "period_end": today,
        "items": items,
    }
