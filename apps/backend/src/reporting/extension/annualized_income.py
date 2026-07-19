"""Reporting-owned annualized income and long-term compensation schedule."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import src.config
from src.audit import normalize_currency_code, to_money
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.platform import raise_bad_request
from src.pricing import (
    ManualValuationComponentType,
    ManualValuationFact,
    ManualValuationLiquidityClass,
    list_current_manual_valuation_facts,
)
from src.reporting.extension import fx_gateway
from src.reporting.extension.reporting_calc import income_bucket
from src.schemas import (
    AnnualizedIncomeScheduleHolding,
    AnnualizedIncomeScheduleIncome,
    AnnualizedIncomeScheduleNetWorthTreatment,
    AnnualizedIncomeScheduleResponse,
)

settings = src.config.settings


async def generate_annualized_income_schedule(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date | None = None,
    currency: str | None = None,
) -> AnnualizedIncomeScheduleResponse:
    """Return report-ready annualized income and restricted compensation."""
    report_date = as_of_date or date.today()
    start_date = report_date - timedelta(days=365)
    income_result = await db.execute(
        select(JournalLine, Account)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .join(Account, JournalLine.account_id == Account.id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.entry_date > start_date)
        .where(JournalEntry.entry_date <= report_date)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
        .where(Account.type == AccountType.INCOME)
    )

    totals = {
        "salary": Decimal("0.00"),
        "bonus": Decimal("0.00"),
        "dividend": Decimal("0.00"),
        "total": Decimal("0.00"),
    }
    reporting_currency = normalize_currency_code(currency or settings.base_currency)
    for line, account in income_result.all():
        line_money = line.money
        signed_amount = line_money.amount if line.direction == Direction.CREDIT else -line_money.amount
        try:
            signed_amount = await fx_gateway.convert_amount(
                db,
                amount=signed_amount,
                currency=line_money.currency.code,
                target_currency=reporting_currency,
                rate_date=report_date,
                average_start=start_date,
                average_end=report_date,
                lazy_load=True,
            )
        except fx_gateway.FxRateError as exc:
            raise_bad_request(str(exc), cause=exc)
        bucket = income_bucket(account.name)
        if bucket:
            totals[bucket] += signed_amount
        totals["total"] += signed_amount

    restricted_types = (
        ManualValuationComponentType.ESOP,
        ManualValuationComponentType.RSU,
        ManualValuationComponentType.STOCK_OPTIONS,
    )
    snapshots = await list_current_manual_valuation_facts(
        db,
        user_id,
        as_of_date=report_date,
        component_types=restricted_types,
        liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
    )

    latest_holdings: dict[tuple[ManualValuationComponentType, str, str], ManualValuationFact] = {}
    for snapshot in snapshots:
        key = (snapshot.component_type, snapshot.source, snapshot.currency)
        latest_holdings.setdefault(key, snapshot)

    holdings: list[AnnualizedIncomeScheduleHolding] = []
    restricted_total = Decimal("0.00")
    for snapshot in latest_holdings.values():
        holdings.append(
            AnnualizedIncomeScheduleHolding(
                ticker=snapshot.source,
                compensation_type=snapshot.component_type.value,
                fair_value=to_money(snapshot.value),
                currency=snapshot.currency,
                valuation_basis=(snapshot.valuation_basis.value if snapshot.valuation_basis else "unspecified"),
                vesting_schedule=snapshot.notes,
                unlock_date=snapshot.reminder_date,
                liquidity_class=snapshot.liquidity_class.value,
                net_worth_treatment="excluded_from_liquid_net_worth_by_default",
            )
        )
        try:
            restricted_total += await fx_gateway.convert_amount(
                db,
                amount=snapshot.value,
                currency=snapshot.currency,
                target_currency=reporting_currency,
                rate_date=report_date,
                lazy_load=True,
            )
        except fx_gateway.FxRateError as exc:
            raise_bad_request(str(exc), cause=exc)

    return AnnualizedIncomeScheduleResponse(
        section_id="annualized_income_long_term",
        label="Annualized Income & Long-Term Compensation",
        as_of_date=report_date,
        trailing_period_start=start_date,
        trailing_period_end=report_date,
        trailing_period_days=365,
        income=AnnualizedIncomeScheduleIncome(
            annualized_salary=to_money(totals["salary"]),
            annualized_bonus=to_money(totals["bonus"]),
            annualized_dividend=to_money(totals["dividend"]),
            annualized_total=to_money(totals["total"]),
            currency=reporting_currency,
            calculation_basis="posted_or_reconciled_income_journal_lines_trailing_12_months",
        ),
        restricted_holdings=holdings,
        restricted_fair_value_total=to_money(restricted_total),
        restricted_fair_value_total_currency=reporting_currency,
        net_worth_treatment=AnnualizedIncomeScheduleNetWorthTreatment(
            liquid_net_worth_default="exclude_restricted_holdings",
            restricted_wealth_basis="manual_valuation_snapshot_fair_value",
            include_restricted_query="/api/reports/balance-sheet?include_restricted=true",
            exclude_restricted_query="/api/reports/balance-sheet?include_restricted=false",
        ),
        notes=[
            "Personal management report only; not tax advice.",
            "Restricted holdings are excluded from liquid net worth by default.",
        ],
    )
