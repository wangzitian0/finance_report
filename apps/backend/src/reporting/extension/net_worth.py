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
from src.observability import ErrorIds, get_logger
from src.pricing import ManualValuationLiquidityClass, PrefetchedFxRates, PricingError, get_exchange_rate_series
from src.reporting.base.types import DEFAULT_INCLUDE_RESTRICTED
from src.reporting.extension._core import _load_accounts, _single_source_currency
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

logger = get_logger(__name__)


def _allocation_source_line(
    line: dict[str, Any],
    *,
    value: Decimal,
    label: str,
    source_type: str,
) -> dict[str, Any]:
    """Return one contributor of an allocation row.

    The line carries no link (#2645). The app chooses the surface from
    ``source_type`` and ``source_id``: the API cannot know the app routes.
    """
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
        ),
    )


def _add_liability_allocation_line(
    grouped: dict[tuple[str, str, str], dict[str, Any]],
    line: dict[str, Any],
    *,
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
        ),
    )


def _allocation_percentage(value: Decimal, net_worth: Decimal) -> Decimal | None:
    if net_worth == Decimal("0.00"):
        return None
    allocation_ratio = Ratio.fraction(value, net_worth)
    return allocation_ratio.to_percent()


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
            currency=target_currency,
        )
    for line in liability_lines:
        _add_liability_allocation_line(grouped, line, currency=target_currency)

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
        # Carry the balance sheet's trust signals so the dashboard surface shows the
        # same opening-balance gate as the balance sheet (AC2.16.4 / #1481).
        "opening_balance_warnings": balance_sheet.get("opening_balance_warnings", []),
        # Same portfolio point-in-time gaps as the balance sheet (#1791 follow-up)
        # -- generate_balance_sheet already ran the same as_of_date/currency
        # through _build_portfolio_market_adjustment_lines above.
        "portfolio_warnings": balance_sheet.get("portfolio_warnings", []),
        # The classes that the scope leaves out, from the same balance sheet (#2645).
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
        .where(active_journal_entry_filter(JournalEntry))
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
        except PricingError as exc:
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


async def _ledger_net_worth_balances(
    db: AsyncSession,
    user_id: UUID,
    point_dates: list[date],
    target_currency: str,
    *,
    liability_names: dict[UUID, str] | None = None,
) -> list[tuple[dict[UUID, Decimal], dict[UUID, Decimal]]]:
    """Return the asset and liability ledger balances by account for each point date."""
    first_point = point_dates[0]
    signed_columns = (
        JournalLine.account_id,
        Account.type,
        Account.name,
        JournalLine.currency,
        JournalLine.direction,
    )

    def movement_query(*extra_columns: Any) -> Any:
        return (
            select(*signed_columns, *extra_columns, func.sum(JournalLine.amount).label("total"))
            .join(Account, JournalLine.account_id == Account.id)
            .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
            .where(Account.user_id == user_id)
            .where(Account.type.in_((AccountType.ASSET, AccountType.LIABILITY)))
            .where(JournalEntry.user_id == user_id)
            .where(active_journal_entry_filter(JournalEntry))
            .where(JournalEntry.source_type != JournalEntrySourceType.FX_REVALUATION)
            .group_by(*signed_columns, *extra_columns)
        )

    opening_rows = (await db.execute(movement_query().where(JournalEntry.entry_date < first_point))).all()
    daily_rows = (
        await db.execute(
            movement_query(JournalEntry.entry_date)
            .where(JournalEntry.entry_date >= first_point)
            .where(JournalEntry.entry_date <= point_dates[-1])
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

    # One rate series per currency, for the point dates on which the currency
    # has a line (the balance sheet asks for no rate before that).
    rates_by_currency: dict[str, dict[date, Decimal]] = {}
    for currency_code, seen_on in first_seen.items():
        if currency_code == target_currency.upper():
            continue
        rate_dates = [point for point in point_dates if point >= seen_on]
        try:
            rates_by_currency[currency_code] = await get_exchange_rate_series(
                db, currency_code, target_currency, rate_dates, lazy_load=True
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
            # The balance sheet keys its rates by the upper-case code and
            # selects lines whose stored code equals that key.
            if line_currency == target_currency.upper():
                rate: Decimal | None = Decimal("1")
            else:
                rate = rates_by_currency.get(line_currency, {}).get(point)
            if rate is None:
                continue
            unrounded[account_id] = unrounded.get(account_id, Decimal("0")) + amount * rate
        assets = {
            account_id: _quantize_money(amount)
            for account_id, amount in unrounded.items()
            if account_types[account_id] == AccountType.ASSET
        }
        liabilities = {
            account_id: _quantize_money(amount)
            for account_id, amount in unrounded.items()
            if account_types[account_id] == AccountType.LIABILITY
        }
        balances.append((assets, liabilities))
    return balances


async def _portfolio_adjustment_totals(
    db: AsyncSession,
    user_id: UUID,
    point_dates: list[date],
    ledger_assets: list[dict[UUID, Decimal]],
    target_currency: str,
) -> list[Decimal]:
    """Return the portfolio market-value adjustment total for each point date.

    The positions are read once. A point without a held position has no
    adjustment. A point with held positions uses the balance-sheet valuation
    unchanged: the price resolution (override, synced price, snapshot) belongs
    to the portfolio package, so it stays one call per held position and date.
    """
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
    """Get historical net worth points.

    For the same stored FX rates and the same ``include_restricted`` scope, each
    point equals ``total_assets`` and ``total_liabilities`` of
    ``generate_balance_sheet`` on the point date: ledger balances at the spot FX
    rate of that date, portfolio market-value adjustments and the manual
    valuations in the scope (#2645). The ledger balances come from a running
    sum, not from one balance sheet per point (#2583). The series does not
    compute net income, unrealized FX or CTA, so an FX miss on an income or
    expense line does not fail it.

    A monthly series holds at most ``MAX_NET_WORTH_MONTHLY_POINTS`` points and
    keeps the latest months. It starts at the first month that has a non-zero
    total, and it always keeps its last point.
    """
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
        .where(Account.user_id == user_id)
        .where(Account.type == breakdown_type)
        .where(JournalEntry.user_id == user_id)
        .where(active_journal_entry_filter(JournalEntry))
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
        except PricingError as exc:
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
