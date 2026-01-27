"""Financial reporting API router."""

from __future__ import annotations

import csv
from datetime import date
from enum import Enum
from io import StringIO
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, union

from src.config import settings
from src.deps import CurrentUserId, DbSession
from src.logger import get_logger
from src.models import AccountType, FxRate
from src.schemas import (
    AccountTrendResponse,
    BalanceSheetResponse,
    BreakdownPeriod,
    BreakdownType,
    CashFlowResponse,
    CategoryBreakdownResponse,
    IncomeStatementResponse,
    TrendPeriod,
)
from src.services.reporting import (
    ReportError,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
    get_account_trend,
    get_category_breakdown,
)
from src.utils import raise_bad_request

router = APIRouter(prefix="/reports", tags=["reports"])
logger = get_logger(__name__)


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


@router.get("/balance-sheet", response_model=BalanceSheetResponse)
async def balance_sheet(
    as_of_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> BalanceSheetResponse:
    """Get balance sheet as of date."""
    try:
        report = await generate_balance_sheet(
            db,
            user_id,
            as_of_date=as_of_date or date.today(),
            currency=currency,
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
            report = await generate_balance_sheet(
                db,
                user_id,
                as_of_date=as_of_date or date.today(),
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
        else:
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
