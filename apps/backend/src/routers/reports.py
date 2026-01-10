"""Financial reporting API router."""

from __future__ import annotations

from datetime import date
import csv
from enum import Enum
from io import StringIO
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db
from src.models import AccountType
from src.schemas import (
    AccountTrendResponse,
    BalanceSheetResponse,
    BreakdownPeriod,
    BreakdownType,
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

router = APIRouter(prefix="/api/reports", tags=["reports"])

# Mock user_id for now (will be replaced with auth)
MOCK_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def get_report_user_id() -> UUID:
    """Return mock user ID in debug mode; require auth otherwise."""
    if settings.debug:
        return MOCK_USER_ID
    raise HTTPException(status_code=501, detail="Reporting requires authentication.")


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
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_report_user_id),
) -> BalanceSheetResponse:
    """Get balance sheet as of date."""
    try:
        report = await generate_balance_sheet(
            db,
            user_id,
            as_of_date=as_of_date or date.today(),
            currency=currency,
        )
        return BalanceSheetResponse(**report)
    except ReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/income-statement", response_model=IncomeStatementResponse)
async def income_statement(
    start_date: date = Query(...),
    end_date: date = Query(...),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_report_user_id),
) -> IncomeStatementResponse:
    """Get income statement for a period."""
    try:
        report = await generate_income_statement(
            db,
            user_id,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
        )
        return IncomeStatementResponse(**report)
    except ReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cash-flow")
async def cash_flow(
    start_date: date = Query(...),
    end_date: date = Query(...),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_report_user_id),
) -> dict[str, object]:
    """Cash flow statement (planned for phase 2)."""
    try:
        return await generate_cash_flow(
            db,
            user_id,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
        )
    except ReportError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.get("/trend", response_model=AccountTrendResponse)
async def account_trend(
    account_id: UUID = Query(...),
    period: TrendPeriod = Query(default=TrendPeriod.MONTHLY),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_report_user_id),
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
        return AccountTrendResponse(**report)
    except ReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/breakdown", response_model=CategoryBreakdownResponse)
async def category_breakdown(
    breakdown_type: BreakdownType = Query(..., alias="type"),
    period: BreakdownPeriod = Query(default=BreakdownPeriod.MONTHLY),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_report_user_id),
) -> CategoryBreakdownResponse:
    """Get income or expense category breakdown."""
    account_type = (
        AccountType.INCOME
        if breakdown_type == BreakdownType.INCOME
        else AccountType.EXPENSE
    )
    try:
        report = await get_category_breakdown(
            db,
            user_id,
            breakdown_type=account_type,
            period=period.value,
            currency=currency,
        )
        return CategoryBreakdownResponse(**report)
    except ReportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/export")
async def export_report(
    report_type: ReportType = Query(...),
    format: ExportFormat = Query(default=ExportFormat.CSV),
    as_of_date: date | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_report_user_id),
) -> StreamingResponse:
    """Export reports in CSV format."""
    if format != ExportFormat.CSV:
        raise HTTPException(status_code=400, detail="Only CSV export is supported")

    output = StringIO()
    writer = csv.writer(output)

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
        writer.writerow(
            ["Total Liabilities", "", report["total_liabilities"], report["currency"]]
        )
        writer.writerow(["Total Equity", "", report["total_equity"], report["currency"]])
        filename = f"balance-sheet-{report['as_of_date']}.csv"
    elif report_type == ReportType.INCOME_STATEMENT:
        if not start_date or not end_date:
            raise HTTPException(
                status_code=400,
                detail="start_date and end_date are required for income statement export",
            )
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
        writer.writerow(
            ["Total Expenses", "", report["total_expenses"], report["currency"]]
        )
        writer.writerow(["Net Income", "", report["net_income"], report["currency"]])
        filename = f"income-statement-{start_date}-to-{end_date}.csv"
    else:
        raise HTTPException(status_code=400, detail="Unsupported report type")

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
