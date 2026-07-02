"""Annualized income & long-term compensation schedule generation.

Computes the trailing-12-month annualized income buckets and restricted
compensation holdings for the personal report package. Extracted from the
reports router route so it is reusable by snapshot assembly; behavior unchanged.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from src.audit.money import to_money
from src.audit.money.currency import normalize_currency_code
from src.config import settings
from src.deps import CurrentUserId, DbSession
from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.models.layer3 import (
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
)
from src.platform import raise_bad_request
from src.schemas import (
    AnnualizedIncomeScheduleHolding,
    AnnualizedIncomeScheduleIncome,
    AnnualizedIncomeScheduleNetWorthTreatment,
    AnnualizedIncomeScheduleResponse,
)
from src.services.fx import FxRateError, convert_amount
from src.services.reporting_calc import income_bucket


async def generate_annualized_income_schedule(
    db: DbSession,
    user_id: CurrentUserId,
    *,
    as_of_date: date | None = None,
) -> AnnualizedIncomeScheduleResponse:
    """Return report-ready annualized income and restricted compensation schedule."""
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
    currency = normalize_currency_code(settings.base_currency)
    for line, account in income_result.all():
        # Currency is the line's own, resolved via the single base-currency SSOT
        # (the previous per-site account/target fallback chain is dropped — only the
        # impossible currency-is-None path differs, since the column is non-null).
        line_money = line.money
        signed_amount = line_money.amount if line.direction == Direction.CREDIT else -line_money.amount
        source_currency = line_money.currency.code
        try:
            signed_amount = await convert_amount(
                db,
                amount=signed_amount,
                currency=source_currency,
                target_currency=currency,
                rate_date=report_date,
                average_start=start_date,
                average_end=report_date,
                lazy_load=True,
            )
        except FxRateError as exc:
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
    restricted_result = await db.execute(
        select(ManualValuationSnapshot)
        .where(ManualValuationSnapshot.user_id == user_id)
        .where(ManualValuationSnapshot.as_of_date <= report_date)
        .where(ManualValuationSnapshot.component_type.in_(restricted_types))
        .where(ManualValuationSnapshot.liquidity_class == ManualValuationLiquidityClass.RESTRICTED)
        .where(ManualValuationSnapshot.superseded_by_id.is_(None))
        .order_by(ManualValuationSnapshot.as_of_date.desc(), ManualValuationSnapshot.created_at.desc())
    )

    latest_holdings: dict[tuple[ManualValuationComponentType, str, str], ManualValuationSnapshot] = {}
    for snapshot in restricted_result.scalars().all():
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
            restricted_total += await convert_amount(
                db,
                amount=snapshot.value,
                currency=snapshot.currency,
                target_currency=currency,
                rate_date=report_date,
                lazy_load=True,
            )
        except FxRateError as exc:
            raise_bad_request(str(exc), cause=exc)
    restricted_total = to_money(restricted_total)

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
            currency=currency,
            calculation_basis="posted_or_reconciled_income_journal_lines_trailing_12_months",
        ),
        restricted_holdings=holdings,
        restricted_fair_value_total=restricted_total,
        restricted_fair_value_total_currency=currency,
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
