"""Reporting-owned annualized income and long-term compensation schedule."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import (
    Currency,
    ExchangeRate,
    Money,
    convert as convert_money_with_rate,
    normalize_currency_code,
    to_money,
)
from src.config_app import get_effective_base_currency
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalLine
from src.ledger.orm.journal import active_journal_entry_filter
from src.observability import ErrorIds, get_logger
from src.platform import raise_bad_request
from src.pricing import (
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    NoObservationError,
    PrefetchedFxRates,
    PricingError,
    list_current_manual_valuation_facts,
)
from src.reporting.extension.reporting_calc import AnnualizedIncomeTotals, income_bucket, resolve_line_currency
from src.schemas import (
    AnnualizedIncomeScheduleHolding,
    AnnualizedIncomeScheduleIncome,
    AnnualizedIncomeScheduleNetWorthTreatment,
    AnnualizedIncomeScheduleResponse,
)

logger = get_logger(__name__)


async def generate_annualized_income_schedule(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date | None = None,
    currency: str | None = None,
    include_restricted_holdings: bool = True,
) -> AnnualizedIncomeScheduleResponse:
    """Return report-ready annualized income and restricted compensation."""
    if as_of_date is None:
        latest_entry_date = await db.scalar(
            select(func.max(JournalEntry.entry_date))
            .where(JournalEntry.user_id == user_id)
            .where(active_journal_entry_filter(JournalEntry))
        )
        report_date = latest_entry_date or date.today()
    else:
        report_date = as_of_date
    start_date = report_date - timedelta(days=365)
    income_result = await db.execute(
        select(JournalLine, Account)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .join(Account, JournalLine.account_id == Account.id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.entry_date > start_date)
        .where(JournalEntry.entry_date <= report_date)
        .where(active_journal_entry_filter(JournalEntry))
        .where(Account.type == AccountType.INCOME)
    )
    income_rows = income_result.all()

    reporting_currency = normalize_currency_code(currency or await get_effective_base_currency(db, user_id=user_id))
    target_ccy = Currency(reporting_currency)
    snapshots = (
        await list_current_manual_valuation_facts(
            db,
            user_id,
            as_of_date=report_date,
            component_types=ManualValuationComponentType.restricted_compensation_types(),
            liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
        )
        if include_restricted_holdings
        else []
    )

    fx_pairs: list[tuple[str, str, date, date | None, date | None]] = []
    resolved_lines: list[tuple[JournalLine, Account, Money]] = []
    for line, account in income_rows:
        line_money = (
            line.money
            if line.currency
            else Money(line.amount, Currency(resolve_line_currency(line, account, base_currency=reporting_currency)))
        )
        resolved_lines.append((line, account, line_money))
        source_currency = line_money.currency.code
        if source_currency != reporting_currency:
            fx_pairs.append((source_currency, reporting_currency, report_date, start_date, report_date))

    prefetched_fx = PrefetchedFxRates(lazy_load=True)
    if fx_pairs:
        try:
            await prefetched_fx.prefetch(db, fx_pairs)
        except PricingError as exc:
            raise_bad_request(str(exc), cause=exc)
    # A restricted holding is outside the liquid net worth. An FX error on it must not
    # fail the schedule: the holding stays listed in its own currency, and the total
    # names it as left out (#2645). An FX error on an income line still fails.
    # Currency -> (warning type, error text) of each holding currency that did not convert.
    unconverted_currencies: dict[str, tuple[str, str]] = {}
    for holding_currency in sorted({normalize_currency_code(s.currency) for s in snapshots} - {reporting_currency}):
        try:
            await prefetched_fx.prefetch(db, [(holding_currency, reporting_currency, report_date, None, None)])
        except PricingError as exc:
            # The same warning types as an excluded balance-sheet valuation (pricing valuation.py).
            warning_type = (
                "missing_fx_rate_excluded_holding"
                if isinstance(exc, NoObservationError)
                else "fx_conversion_failed_excluded_holding"
            )
            unconverted_currencies[holding_currency] = (warning_type, str(exc))
            logger.warning(
                "Restricted holding currency did not convert; the schedule total leaves it out",
                error_id=ErrorIds.REPORT_FX_FALLBACK,
                error_type=type(exc).__name__,
                warning_type=warning_type,
                currency=holding_currency,
                target_currency=reporting_currency,
                as_of_date=report_date.isoformat(),
                error=str(exc),
            )

    totals = AnnualizedIncomeTotals()
    for line, account, line_money in resolved_lines:
        source_currency = line_money.currency.code
        if source_currency != reporting_currency:
            rate = prefetched_fx.get_rate(source_currency, reporting_currency, report_date, start_date, report_date)
            if rate is None:
                # The prefetch above raised for each missing income rate, so no line converts at 1:1.
                raise_bad_request(f"No FX rate available for {source_currency}/{reporting_currency}")
            converted_amount = convert_money_with_rate(
                line_money,
                ExchangeRate(line_money.currency, target_ccy, rate),
            ).amount
        else:
            converted_amount = line_money.amount
        signed_amount = converted_amount if line.direction == Direction.CREDIT else -converted_amount
        totals.add(income_bucket(account.name), signed_amount)

    holdings: list[AnnualizedIncomeScheduleHolding] = []
    restricted_total = Decimal("0.00")
    left_out_of_total: list[dict[str, str]] = []
    for snapshot in snapshots:
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
        holding_currency = normalize_currency_code(snapshot.currency)
        if holding_currency == reporting_currency:
            restricted_total += snapshot.value
            continue
        gap = unconverted_currencies.get(holding_currency)
        holding_rate = None if gap else prefetched_fx.get_rate(holding_currency, reporting_currency, report_date)
        if holding_rate is None:
            warning_type, message = gap or ("missing_fx_rate_excluded_holding", "No FX rate after prefetch")
            left_out_of_total.append(
                {
                    "type": warning_type,
                    "component_type": snapshot.component_type.value,
                    "source": snapshot.source,
                    "currency": holding_currency,
                    "target_currency": reporting_currency,
                    "as_of_date": report_date.isoformat(),
                    "amount": str(to_money(snapshot.value)),
                    "message": message,
                }
            )
            continue
        holding_ccy = Currency(holding_currency)
        restricted_total += convert_money_with_rate(
            Money(snapshot.value, holding_ccy),
            ExchangeRate(holding_ccy, target_ccy, holding_rate),
        ).amount

    return AnnualizedIncomeScheduleResponse(
        section_id="annualized_income_long_term",
        label="Annualized Income & Long-Term Compensation",
        as_of_date=report_date,
        trailing_period_start=start_date,
        trailing_period_end=report_date,
        trailing_period_days=365,
        income=AnnualizedIncomeScheduleIncome(
            annualized_salary=to_money(totals.salary),
            annualized_bonus=to_money(totals.bonus),
            annualized_dividend=to_money(totals.dividend),
            annualized_total=to_money(totals.total),
            currency=reporting_currency,
            calculation_basis="posted_or_reconciled_income_journal_lines_trailing_12_months",
        ),
        restricted_holdings=holdings,
        restricted_fair_value_total=to_money(restricted_total),
        restricted_fair_value_total_currency=reporting_currency,
        restricted_fair_value_total_excludes=left_out_of_total,
        net_worth_treatment=AnnualizedIncomeScheduleNetWorthTreatment(
            liquid_net_worth_default="exclude_restricted_holdings",
            restricted_wealth_basis="manual_valuation_snapshot_fair_value",
            include_restricted_query="/api/reports/balance-sheet?include_restricted=true",
            exclude_restricted_query="/api/reports/balance-sheet?include_restricted=false",
        ),
        notes=[
            "Personal management report only; not tax advice.",
            "Restricted holdings are excluded from liquid net worth by default.",
            *(
                [
                    f"The restricted fair-value total leaves out these holdings, which did not convert to "
                    f"{reporting_currency} on {report_date.isoformat()}: "
                    + "; ".join(
                        f"{row['source']} ({row['currency']} {Decimal(row['amount']):,.2f})"
                        for row in left_out_of_total
                    )
                    + "."
                ]
                if left_out_of_total
                else []
            ),
        ],
    )
