"""Financial reporting API router."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from io import StringIO
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, union

from src.config import settings
from src.deps import CurrentUserId, DbSession
from src.logger import get_logger
from src.models import Account, AccountType, Direction, FxRate, JournalEntry, JournalEntryStatus, JournalLine
from src.models.layer3 import (
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
)
from src.schemas import (
    AccountTrendResponse,
    AnnualizedIncomeScheduleHolding,
    AnnualizedIncomeScheduleIncome,
    AnnualizedIncomeScheduleNetWorthTreatment,
    AnnualizedIncomeScheduleResponse,
    BalanceSheetResponse,
    BreakdownPeriod,
    BreakdownType,
    CashFlowResponse,
    CategoryBreakdownResponse,
    IncomeStatementResponse,
    NetWorthGranularity,
    NetWorthTimeSeriesResponse,
    PersonalReportPackageContractResponse,
    TrendPeriod,
)
from src.services.market_data import ensure_market_data_fresh
from src.services.reporting import (
    ReportError,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
    get_account_trend,
    get_category_breakdown,
    get_net_worth_timeseries,
)
from src.utils import raise_bad_request

router = APIRouter(prefix="/reports", tags=["reports"])
logger = get_logger(__name__)


def _target_currency_pair(currency: str | None) -> list[str]:
    target = (currency or settings.base_currency).strip().upper()
    base = settings.base_currency.strip().upper()
    if target == base:
        return []
    return [f"{target}/{base}"]


async def _ensure_report_market_data_fresh(
    db: DbSession,
    user_id: CurrentUserId,
    *,
    currency: str | None,
    end_date: date,
) -> None:
    has_report_subjects = await db.scalar(select(Account.id).where(Account.user_id == user_id).limit(1))
    await ensure_market_data_fresh(
        db,
        user_id=user_id,
        end_date=end_date,
        include_default_fx=False,
        extra_fx_pairs=_target_currency_pair(currency) if has_report_subjects is not None else [],
    )


@router.get("/currencies", response_model=list[str])
async def get_available_currencies(
    db: DbSession = None,
) -> list[str]:
    """Get list of currencies with FX data available."""
    base_stmt = select(FxRate.base_currency).distinct()
    quote_stmt = select(FxRate.quote_currency).distinct()
    combined = union(base_stmt, quote_stmt).subquery()
    result = await db.execute(select(combined.c.base_currency).order_by(combined.c.base_currency))
    currencies = [row[0] for row in result.fetchall()]

    if settings.base_currency not in currencies:
        currencies = [settings.base_currency] + currencies

    return currencies


class ExportFormat(str, Enum):
    """Supported export formats."""

    CSV = "csv"


class ReportType(str, Enum):
    """Supported report types for export."""

    BALANCE_SHEET = "balance-sheet"
    INCOME_STATEMENT = "income-statement"


PERSONAL_REPORT_PACKAGE_CONTRACT: dict = {
    "package_id": "personal-financial-report-package",
    "version": "1.0",
    "period_semantics": {
        "start_date": "required for period sections",
        "end_date": "required for period sections",
        "as_of_date": "required for point-in-time sections",
        "currency": "ISO-4217 code; defaults to base currency when omitted",
        "decimal_serialization": "string",
    },
    "sections": [
        {
            "section_id": "balance_sheet",
            "label": "Balance Sheet",
            "owner_epic": "EPIC-005",
            "period_type": "as_of",
            "source_endpoint": "/api/reports/balance-sheet",
            "status": "ready",
            "decimal_total_fields": ["total_assets", "total_liabilities", "total_equity", "equation_delta"],
        },
        {
            "section_id": "income_statement",
            "label": "Income Statement",
            "owner_epic": "EPIC-005",
            "period_type": "period",
            "source_endpoint": "/api/reports/income-statement",
            "status": "ready",
            "decimal_total_fields": ["total_income", "total_expenses", "net_income"],
        },
        {
            "section_id": "cash_flow",
            "label": "Cash Flow",
            "owner_epic": "EPIC-005",
            "period_type": "period",
            "source_endpoint": "/api/reports/cash-flow",
            "status": "ready",
            "decimal_total_fields": [
                "operating_activities",
                "investing_activities",
                "financing_activities",
                "net_cash_flow",
                "beginning_cash",
                "ending_cash",
            ],
        },
        {
            "section_id": "investment_performance",
            "label": "Investment Performance",
            "owner_epic": "EPIC-017",
            "period_type": "period_and_as_of",
            "source_endpoint": "/api/portfolio/performance/report-schedule",
            "status": "ready",
            "decimal_total_fields": [
                "xirr",
                "time_weighted_return",
                "money_weighted_return",
                "realized_pnl",
                "unrealized_pnl",
                "dividend_income",
            ],
        },
        {
            "section_id": "annualized_income_long_term",
            "label": "Annualized Income & Long-Term Compensation",
            "owner_epic": "EPIC-011",
            "period_type": "trailing_12_months_and_as_of",
            "source_endpoint": "/api/reports/package/annualized-income-schedule",
            "status": "ready",
            "blocking_issue": None,
            "decimal_total_fields": [
                "annualized_salary",
                "annualized_bonus",
                "annualized_dividend",
                "annualized_total",
                "restricted_fair_value",
            ],
        },
        {
            "section_id": "notes",
            "label": "Notes & Disclosures",
            "owner_epic": "EPIC-005",
            "period_type": "package",
            "source_endpoint": "/api/reports/package/notes",
            "status": "planned",
            "blocking_issue": "#571",
            "decimal_total_fields": [],
        },
        {
            "section_id": "traceability_appendix",
            "label": "Traceability Appendix",
            "owner_epic": "EPIC-018",
            "period_type": "package",
            "source_endpoint": "/api/reports/package/traceability",
            "status": "planned",
            "blocking_issue": "#572",
            "decimal_total_fields": [],
        },
    ],
    "export_contract": {
        "formats": ["json", "csv"],
        "csv_columns": ["package_id", "section_id", "line_id", "label", "amount", "currency", "source_state"],
    },
}


def _annualized_income_bucket(account_name: str) -> str | None:
    normalized = account_name.casefold()
    if "salary" in normalized or "payroll" in normalized:
        return "salary"
    if "bonus" in normalized:
        return "bonus"
    if "dividend" in normalized:
        return "dividend"
    return None


@router.get("/package/contract", response_model=PersonalReportPackageContractResponse)
def personal_report_package_contract() -> PersonalReportPackageContractResponse:
    """Return the stable package-level API/export contract."""
    return PersonalReportPackageContractResponse(**PERSONAL_REPORT_PACKAGE_CONTRACT)


@router.get("/package/annualized-income-schedule", response_model=AnnualizedIncomeScheduleResponse)
async def annualized_income_schedule(
    as_of_date: date | None = Query(default=None),
    db: DbSession = None,
    user_id: CurrentUserId = None,
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
    currency = settings.base_currency
    for line, account in income_result.all():
        signed_amount = line.amount if line.direction == Direction.CREDIT else -line.amount
        bucket = _annualized_income_bucket(account.name)
        if bucket:
            totals[bucket] += signed_amount
        totals["total"] += signed_amount
        currency = line.currency or account.currency or currency

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
        .order_by(ManualValuationSnapshot.as_of_date.desc(), ManualValuationSnapshot.created_at.desc())
    )

    latest_holdings: dict[tuple[ManualValuationComponentType, str, str], ManualValuationSnapshot] = {}
    for snapshot in restricted_result.scalars().all():
        key = (snapshot.component_type, snapshot.source, snapshot.currency)
        latest_holdings.setdefault(key, snapshot)

    holdings = [
        AnnualizedIncomeScheduleHolding(
            ticker=snapshot.source,
            compensation_type=snapshot.component_type.value,
            fair_value=snapshot.value.quantize(Decimal("0.01")),
            currency=snapshot.currency,
            valuation_basis="manual_valuation_snapshot",
            vesting_schedule=snapshot.notes,
            unlock_date=snapshot.reminder_date,
            liquidity_class=snapshot.liquidity_class.value,
            net_worth_treatment="excluded_from_liquid_net_worth_by_default",
        )
        for snapshot in latest_holdings.values()
    ]
    restricted_total = sum(
        (holding.fair_value for holding in holdings if holding.currency == currency),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"))

    return AnnualizedIncomeScheduleResponse(
        section_id="annualized_income_long_term",
        label="Annualized Income & Long-Term Compensation",
        as_of_date=report_date,
        trailing_period_start=start_date,
        trailing_period_end=report_date,
        trailing_period_days=365,
        income=AnnualizedIncomeScheduleIncome(
            annualized_salary=totals["salary"].quantize(Decimal("0.01")),
            annualized_bonus=totals["bonus"].quantize(Decimal("0.01")),
            annualized_dividend=totals["dividend"].quantize(Decimal("0.01")),
            annualized_total=totals["total"].quantize(Decimal("0.01")),
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


@router.get("/balance-sheet", response_model=BalanceSheetResponse)
async def balance_sheet(
    as_of_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    include_restricted: bool = Query(default=True),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> BalanceSheetResponse:
    """Get balance sheet as of date."""
    try:
        report_date = as_of_date or date.today()
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=report_date)
        report = await generate_balance_sheet(
            db,
            user_id,
            as_of_date=report_date,
            currency=currency,
            include_restricted=include_restricted,
        )
    except ReportError as exc:
        logger.warning(
            "Balance sheet generation failed",
            as_of_date=str(as_of_date),
            currency=currency,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)
    return BalanceSheetResponse(**report)


@router.get("/income-statement", response_model=IncomeStatementResponse)
async def income_statement(
    start_date: date = Query(...),
    end_date: date = Query(...),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    tags: list[str] | None = Query(default=None, alias="tags"),
    account_type: AccountType | None = Query(default=None, alias="account_type"),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> IncomeStatementResponse:
    """Get income statement for a period with optional filtering."""
    try:
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=end_date)
        report = await generate_income_statement(
            db,
            user_id,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
            tags=tags,
            account_type=account_type,
        )
    except ReportError as exc:
        logger.warning(
            "Income statement generation failed",
            start_date=str(start_date),
            end_date=str(end_date),
            currency=currency,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)
    return IncomeStatementResponse(**report)


@router.get("/cash-flow", response_model=CashFlowResponse)
async def cash_flow(
    start_date: date = Query(...),
    end_date: date = Query(...),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> CashFlowResponse:
    """Get cash flow statement for a period."""
    try:
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=end_date)
        report = await generate_cash_flow(
            db,
            user_id,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
        )
    except ReportError as exc:
        logger.warning(
            "Cash flow generation failed",
            start_date=str(start_date),
            end_date=str(end_date),
            currency=currency,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)
    return CashFlowResponse(**report)


@router.get("/trend", response_model=AccountTrendResponse)
async def account_trend(
    account_id: UUID = Query(...),
    period: TrendPeriod = Query(default=TrendPeriod.MONTHLY),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> AccountTrendResponse:
    """Get account trend data."""
    try:
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=date.today())
        report = await get_account_trend(
            db,
            user_id,
            account_id=account_id,
            period=period.value,
            currency=currency,
        )
    except ReportError as exc:
        logger.warning(
            "Account trend generation failed",
            account_id=str(account_id),
            period=period.value,
            currency=currency,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)
    return AccountTrendResponse(**report)


@router.get("/net-worth/timeseries", response_model=NetWorthTimeSeriesResponse)
async def net_worth_timeseries(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    granularity: NetWorthGranularity = Query(default=NetWorthGranularity.MONTHLY),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> NetWorthTimeSeriesResponse:
    """Get daily or monthly net worth time-series."""
    try:
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=to_date)
        report = await get_net_worth_timeseries(
            db,
            user_id,
            start_date=from_date,
            end_date=to_date,
            granularity=granularity.value,
            currency=currency,
        )
    except ReportError as exc:
        logger.warning(
            "Net worth time-series generation failed",
            from_date=str(from_date),
            to_date=str(to_date),
            granularity=granularity.value,
            currency=currency,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)
    return NetWorthTimeSeriesResponse(**report)


@router.get("/breakdown", response_model=CategoryBreakdownResponse)
async def category_breakdown(
    breakdown_type: BreakdownType = Query(..., alias="type"),
    period: BreakdownPeriod = Query(default=BreakdownPeriod.MONTHLY),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> CategoryBreakdownResponse:
    """Get income or expense category breakdown."""
    account_type = AccountType.INCOME if breakdown_type == BreakdownType.INCOME else AccountType.EXPENSE
    try:
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=date.today())
        report = await get_category_breakdown(
            db,
            user_id,
            breakdown_type=account_type,
            period=period.value,
            currency=currency,
        )
    except ReportError as exc:
        logger.warning(
            "Category breakdown generation failed",
            breakdown_type=breakdown_type.value,
            period=period.value,
            currency=currency,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)
    return CategoryBreakdownResponse(**report)


@router.get("/export")
async def export_report(
    report_type: ReportType = Query(...),
    format: ExportFormat = Query(default=ExportFormat.CSV),
    as_of_date: date | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> StreamingResponse:
    """Export reports in CSV format."""
    output = StringIO()
    writer = csv.writer(output)

    try:
        if report_type == ReportType.BALANCE_SHEET:
            report_date = as_of_date or date.today()
            await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=report_date)
            report = await generate_balance_sheet(
                db,
                user_id,
                as_of_date=report_date,
                currency=currency,
            )
            writer.writerow(["section", "account", "amount", "currency"])
            for section, lines in (
                ("Assets", report["assets"]),
                ("Liabilities", report["liabilities"]),
                ("Equity", report["equity"]),
            ):
                for line in lines:
                    writer.writerow([section, line["name"], line["amount"], report["currency"]])
            writer.writerow(["Total Assets", "", report["total_assets"], report["currency"]])
            writer.writerow(["Total Liabilities", "", report["total_liabilities"], report["currency"]])
            writer.writerow(["Total Equity", "", report["total_equity"], report["currency"]])
            filename = f"balance-sheet-{report['as_of_date']}.csv"
        elif report_type == ReportType.INCOME_STATEMENT:
            if not start_date or not end_date:
                raise_bad_request("start_date and end_date are required for income statement export")
            await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=end_date)
            report = await generate_income_statement(
                db,
                user_id,
                start_date=start_date,
                end_date=end_date,
                currency=currency,
            )
            writer.writerow(["section", "account", "amount", "currency"])
            for section, lines in (("Income", report["income"]), ("Expenses", report["expenses"])):
                for line in lines:
                    writer.writerow([section, line["name"], line["amount"], report["currency"]])
            writer.writerow(["Total Income", "", report["total_income"], report["currency"]])
            writer.writerow(["Total Expenses", "", report["total_expenses"], report["currency"]])
            writer.writerow(["Net Income", "", report["net_income"], report["currency"]])
            filename = f"income-statement-{start_date}-to-{end_date}.csv"
        else:  # pragma: no cover - FastAPI enum validation rejects unsupported values first.
            raise_bad_request("Unsupported report type")
    except ReportError as exc:
        logger.warning(
            "Report export failed",
            report_type=report_type.value,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)

    content = output.getvalue()
    output.close()
    return StreamingResponse(
        StringIO(content),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{report_type}/snapshots")
async def list_report_snapshots(
    report_type: str,
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> list[dict]:
    """List available report snapshots for a given report type.

    AC18.4.2: ReportSnapshot (Layer 4) is queryable via API.
    """
    from sqlalchemy import select as sa_select

    from src.models.layer4 import ReportSnapshot

    stmt = (
        sa_select(ReportSnapshot)
        .where(ReportSnapshot.report_type == report_type)
        .where(ReportSnapshot.user_id == user_id)
        .order_by(ReportSnapshot.created_at.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    snapshots = result.scalars().all()

    return [
        {
            "id": str(s.id),
            "report_type": s.report_type.value if hasattr(s.report_type, "value") else str(s.report_type),
            "as_of_date": s.as_of_date.isoformat() if s.as_of_date else None,
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "rule_version_id": str(s.rule_version_id),
            "is_latest": s.is_latest,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in snapshots
    ]
