"""Net-worth allocation, trends, timeseries, and category breakdown."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.error_ids import ErrorIds
from src.logger import get_logger
from src.models.account import Account, AccountType
from src.models.journal import JournalEntry, JournalLine
from src.models.layer3 import (
    ManualValuationLiquidityClass,
)
from src.ratio import Ratio
from src.services.fx import (
    FxRateError,
    PrefetchedFxRates,
)
from src.services.reporting._core import _REPORT_STATUSES, _load_accounts, _single_source_currency
from src.services.reporting.balance_sheet import generate_balance_sheet
from src.services.reporting.portfolio_market import _portfolio_market_basis_by_account
from src.services.reporting_calc import (
    MAX_NET_WORTH_DAILY_POINTS,
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
    allocation_ratio = Ratio.fraction(value, net_worth)
    return allocation_ratio.to_percent()


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
