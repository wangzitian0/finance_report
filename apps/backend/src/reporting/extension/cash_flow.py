"""Cash flow statement generation."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import Account, AccountType, JournalEntry, JournalLine
from src.observability import ErrorIds, get_logger
from src.reporting.extension import fx_gateway
from src.reporting.extension._core import _REPORT_STATUSES, _line_total
from src.reporting.extension.reporting_calc import (
    ReportError,
    _normalize_currency,
    _quantize_money,
    _signed_amount,
)

logger = get_logger(__name__)


def _cash_flow_agg_stmt(user_id: UUID, *date_conditions: Any) -> Select[Any]:
    """Per-(account, currency, direction) journal-line sums for the cash-flow
    statement: report-eligible entries scoped by the given date conditions."""
    stmt = (
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
        .group_by(Account.id, JournalLine.currency, JournalLine.direction)
    )
    for condition in date_conditions:
        stmt = stmt.where(condition)
    return stmt


def _accumulate_period_balances(
    rows: Iterable[Any],
    account_id_to_account: dict[UUID, Account],
    fx_rates: fx_gateway.PrefetchedFxRates,
    *,
    target_currency: str,
    rate_date: date,
) -> dict[UUID, Decimal]:
    """Convert each aggregated row to ``target_currency`` at ``rate_date`` and
    accumulate signed balances per account. Raises ReportError on a missing rate."""
    balances: dict[UUID, Decimal] = {}
    for row in rows:
        rate = fx_rates.get_rate(row.currency, target_currency, rate_date)
        if rate is None:
            if row.currency.upper() == target_currency:
                rate = Decimal("1")
            else:
                raise ReportError(f"No FX rate available for {row.currency}/{target_currency} on {rate_date}")
        converted = Decimal(str(row.total)) * rate
        account = account_id_to_account.get(row.account_id)
        if account:
            balances[row.account_id] = balances.get(row.account_id, Decimal("0")) + _signed_amount(
                account.type, row.direction, converted
            )
    return balances


async def generate_cash_flow(
    db: AsyncSession,
    user_id: UUID,
    *,
    start_date: date,
    end_date: date,
    currency: str | None = None,
    cash_account_ids: frozenset[UUID] | None = None,
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

    rows_before = (await db.execute(_cash_flow_agg_stmt(user_id, JournalEntry.entry_date < start_date))).all()
    rows_during = (
        await db.execute(
            _cash_flow_agg_stmt(user_id, JournalEntry.entry_date >= start_date, JournalEntry.entry_date <= end_date)
        )
    ).all()
    rows_ending = (await db.execute(_cash_flow_agg_stmt(user_id, JournalEntry.entry_date <= end_date))).all()

    fx_needs: list[tuple[str, str, date, date | None, date | None]] = []
    for rows, rate_date in ((rows_before, start_date), (rows_during, end_date), (rows_ending, end_date)):
        fx_needs.extend(
            (row.currency, target_currency, rate_date, None, None)
            for row in rows
            if row.currency.upper() != target_currency
        )

    fx_rates = fx_gateway.PrefetchedFxRates(lazy_load=True)
    if fx_needs:
        try:
            await fx_rates.prefetch(db, fx_needs)
        except fx_gateway.FxRateError as exc:
            logger.error(
                "FX pre-fetch failed for cash flow",
                error_id=ErrorIds.REPORT_GENERATION_FAILED,
                error=str(exc),
            )
            raise ReportError(str(exc)) from exc

    balances_before = _accumulate_period_balances(
        rows_before, account_id_to_account, fx_rates, target_currency=target_currency, rate_date=start_date
    )
    activity_movements = _accumulate_period_balances(
        rows_during, account_id_to_account, fx_rates, target_currency=target_currency, rate_date=end_date
    )
    balances_ending = _accumulate_period_balances(
        rows_ending, account_id_to_account, fx_rates, target_currency=target_currency, rate_date=end_date
    )

    beginning_cash = Decimal("0")
    ending_cash = Decimal("0")
    cash_keywords = ("cash", "bank", "checking", "savings", "money market", "petty cash")

    def is_cash_account(account: Account) -> bool:
        if account.type != AccountType.ASSET:
            return False
        if cash_account_ids is not None:
            return account.id in cash_account_ids
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

    operating_total = _line_total(operating_items)
    investing_total = _line_total(investing_items)
    financing_total = _line_total(financing_items)
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
