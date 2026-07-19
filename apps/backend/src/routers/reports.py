"""Financial reporting API router."""

from __future__ import annotations

import asyncio
import csv
import json
from datetime import UTC, date, datetime
from enum import Enum
from io import StringIO
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, union

from src.composition import observed_fx_pairs
from src.config import settings
from src.deps import CurrentUserId, DbSession, Pagination
from src.ledger import Account, AccountType
from src.observability import get_logger, track as _track_analytics
from src.platform import raise_bad_request, raise_not_found
from src.portfolio import active_stock_symbols
from src.pricing import ensure_market_data_fresh
from src.pricing.orm.market_data import FxRate
from src.reporting import (
    PackageAssembler,
    PackageDocumentVersionError,
    ReportError,
    ReportingSnapshotService,
    ReportSnapshot,
    ReportType as SnapshotReportType,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
    get_account_lineage,
    get_account_trend,
    get_category_breakdown,
    get_net_worth_allocation_schedule,
    get_net_worth_timeseries,
    package_currency as _package_currency,
    package_dates as _package_dates,
    package_snapshot_csv as _package_snapshot_csv,
    package_snapshot_response as _package_snapshot_response,
    package_snapshot_summary as _package_snapshot_summary,
)
from src.schemas import (
    AccountLineageResponse,
    AccountTrendResponse,
    BalanceSheetResponse,
    BreakdownPeriod,
    BreakdownType,
    CashFlowResponse,
    CategoryBreakdownResponse,
    IncomeStatementResponse,
    NetWorthAllocationResponse,
    NetWorthGranularity,
    NetWorthTimeSeriesResponse,
    PersonalReportingFrameworkId,
    PersonalReportPackageDocument,
    PersonalReportPackageDocumentLifecycle,
    PersonalReportPackageGenerateRequest,
    PersonalReportPackageSnapshotResponse,
    PersonalReportPackageSnapshotSummary,
    ReportSnapshotSummary,
    TrendPeriod,
)
from src.schemas.streaming import ExportStreamEnvelope, ExportStreamMediaType

router = APIRouter(prefix="/reports", tags=["reports"])
logger = get_logger(__name__)
DEFAULT_INCLUDE_RESTRICTED = False


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
    try:
        fx_pairs = set(await observed_fx_pairs(db, user_id, include_default=False))
        fx_pairs.update(_target_currency_pair(currency) if has_report_subjects is not None else [])
        stock_symbols = await active_stock_symbols(db, user_id)
        await ensure_market_data_fresh(
            db,
            fx_pairs=list(fx_pairs),
            stock_symbols=stock_symbols,
            end_date=end_date,
        )
    except asyncio.CancelledError:
        # Never swallow cancellation (request disconnect / shutdown): let it
        # propagate so FastAPI can unwind the request properly.
        raise
    except Exception as exc:  # noqa: BLE001 - freshness is best-effort enrichment
        # #1388: a failed market-data/FX refresh (provider error, unresolvable
        # symbol, malformed FX pair, network blip) must not turn report
        # generation into a 500. The report endpoints only catch ReportError, so
        # any other exception escaping here surfaced as an unhandled 500 the
        # moment an account held a position. Fall back to already-stored data
        # (possibly stale) and let the report render. Keep the traceback
        # (exc_info) since these failures can be hard to reproduce.
        logger.warning(
            "Market-data freshness sync failed; rendering report with stored data",
            error=str(exc),
            user_id=str(user_id),
            end_date=str(end_date),
            exc_info=True,
        )


@router.get("/currencies", response_model=list[str])
async def get_available_currencies(
    *,
    db: DbSession,
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


class PackageSnapshotExportFormat(str, Enum):
    """Supported saved package snapshot export formats."""

    JSON = "json"
    CSV = "csv"


class ExportReportType(str, Enum):
    """Supported report types for export."""

    BALANCE_SHEET = "balance-sheet"
    INCOME_STATEMENT = "income-statement"
    CASH_FLOW = "cash-flow"


@router.get("/package", response_model=PersonalReportPackageDocument)
async def preview_personal_report_package(
    framework_id: PersonalReportingFrameworkId = PersonalReportingFrameworkId.US_GAAP_LIKE,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    as_of_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    include_restricted: bool = Query(default=False),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> PersonalReportPackageDocument:
    """Build the one typed preview document without persisting a snapshot."""
    report_start, report_end, report_as_of = _package_dates(
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
    )
    target_currency = _package_currency(currency)
    await _ensure_report_market_data_fresh(db, user_id, currency=target_currency, end_date=report_as_of)
    return await PackageAssembler().assemble(
        db,
        user_id=user_id,
        framework_id=framework_id,
        start_date=report_start,
        end_date=report_end,
        as_of_date=report_as_of,
        currency=target_currency,
        include_restricted=include_restricted,
    )


@router.post("/package/generate", response_model=PersonalReportPackageSnapshotResponse)
async def generate_personal_report_package_snapshot(
    db: DbSession,
    user_id: CurrentUserId,
    request: PersonalReportPackageGenerateRequest,
) -> PersonalReportPackageSnapshotResponse:
    """Generate and persist an immutable personal report package snapshot."""
    report_start, report_end, report_as_of = _package_dates(
        start_date=request.start_date,
        end_date=request.end_date,
        as_of_date=request.as_of_date,
    )
    target_currency = _package_currency(request.currency)
    snapshot_id = uuid4()
    frozen_at = datetime.now(UTC)
    await _ensure_report_market_data_fresh(db, user_id, currency=target_currency, end_date=report_as_of)
    document = await PackageAssembler().assemble(
        db=db,
        user_id=user_id,
        framework_id=request.framework_id,
        start_date=report_start,
        end_date=report_end,
        as_of_date=report_as_of,
        currency=target_currency,
        include_restricted=request.include_restricted,
        lifecycle=PersonalReportPackageDocumentLifecycle.FROZEN,
        snapshot_id=snapshot_id,
        frozen_at=frozen_at,
    )
    snapshot = await ReportingSnapshotService().create_snapshot(
        db,
        user_id=user_id,
        report_type=SnapshotReportType.PACKAGE,
        start_date=report_start,
        as_of_date=report_as_of,
        rule_version_id=None,
        report_data=document.model_dump(mode="json"),
        ttl_seconds=0,
        snapshot_id=snapshot_id,
    )
    await db.commit()
    # BE->OpenPanel: server-authoritative `report_generated` (fires even if the
    # browser event is blocked). The official SDK's track() is itself non-blocking
    # (its own daemon send-thread), config-gated + never raises — so calling it
    # inline can't add latency or break report generation, and the handler stays
    # safe to call directly (tests) without a FastAPI BackgroundTasks instance.
    _track_analytics(
        "report_generated",
        {"framework_id": request.framework_id.value, "currency": target_currency},
    )
    try:
        return _package_snapshot_response(snapshot)
    except PackageDocumentVersionError as exc:  # pragma: no cover - just-written documents validate above.
        raise_bad_request(str(exc), cause=exc)


@router.get("/package/snapshots", response_model=list[PersonalReportPackageSnapshotSummary])
async def list_personal_report_package_snapshots(
    db: DbSession,
    user_id: CurrentUserId,
    pagination: Pagination,
) -> list[PersonalReportPackageSnapshotSummary]:
    """List saved personal report package snapshots for the current user."""
    stmt = (
        select(ReportSnapshot)
        .where(ReportSnapshot.user_id == user_id)
        .where(ReportSnapshot.report_type == SnapshotReportType.PACKAGE)
        # Stable tiebreaker (id) so offset pagination is deterministic when
        # created_at timestamps tie — otherwise pages could drop/duplicate rows.
        .order_by(ReportSnapshot.created_at.desc(), ReportSnapshot.id.desc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    result = await db.execute(stmt)
    return [_package_snapshot_summary(snapshot) for snapshot in result.scalars().all()]


@router.get("/package/snapshots/{snapshot_id}", response_model=PersonalReportPackageSnapshotResponse)
async def get_personal_report_package_snapshot(
    snapshot_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> PersonalReportPackageSnapshotResponse:
    """Return one saved package snapshot without recalculating live report data."""
    snapshot = await db.scalar(
        select(ReportSnapshot)
        .where(ReportSnapshot.id == snapshot_id)
        .where(ReportSnapshot.user_id == user_id)
        .where(ReportSnapshot.report_type == SnapshotReportType.PACKAGE)
    )
    if snapshot is None:
        raise_not_found("Package snapshot")
    try:
        return _package_snapshot_response(snapshot)
    except PackageDocumentVersionError as exc:
        raise_bad_request(str(exc), cause=exc)


@router.get("/package/snapshots/{snapshot_id}/export")
async def export_personal_report_package_snapshot(
    snapshot_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
    format: PackageSnapshotExportFormat = Query(default=PackageSnapshotExportFormat.CSV),
) -> StreamingResponse:
    """Export a saved package snapshot as JSON or CSV."""
    snapshot = await get_personal_report_package_snapshot(snapshot_id=snapshot_id, db=db, user_id=user_id)
    stem = f"personal-report-package-{snapshot.framework_id.value}-{snapshot.as_of_date}-{snapshot.id}"
    if format == PackageSnapshotExportFormat.JSON:
        content = json.dumps(snapshot.model_dump(mode="json"), sort_keys=True)
        envelope = ExportStreamEnvelope(media_type=ExportStreamMediaType.JSON, filename=f"{stem}.json")
    else:
        content = _package_snapshot_csv(snapshot)
        envelope = ExportStreamEnvelope(media_type=ExportStreamMediaType.CSV, filename=f"{stem}.csv")
    return StreamingResponse(
        StringIO(content),
        media_type=envelope.media_type.value,
        headers=envelope.to_headers(),
    )


@router.get("/balance-sheet", response_model=BalanceSheetResponse)
async def balance_sheet(
    as_of_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    include_restricted: bool = Query(default=DEFAULT_INCLUDE_RESTRICTED),
    *,
    db: DbSession,
    user_id: CurrentUserId,
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
    await db.commit()
    return BalanceSheetResponse.model_validate(report)


@router.get("/account-lineage", response_model=AccountLineageResponse)
async def account_lineage(
    account_id: UUID = Query(...),
    as_of_date: date | None = Query(default=None),
    start_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> AccountLineageResponse:
    """List the journal lines contributing to one account's report balance.

    Powers Balance Sheet / Income Statement amount drill-down: each returned
    line carries a ``journal_line`` evidence anchor that the UI hands to
    ``GET /api/evidence/lineage`` to reach statement transactions and source
    documents.
    """
    report_date = as_of_date or date.today()
    try:
        report = await get_account_lineage(
            db,
            user_id,
            account_id,
            as_of_date=report_date,
            start_date=start_date,
            currency=currency,
        )
    except ReportError as exc:
        raise_not_found(f"Account {account_id}", cause=exc)
    return AccountLineageResponse.model_validate(report)


@router.get("/income-statement", response_model=IncomeStatementResponse)
async def income_statement(
    start_date: date = Query(...),
    end_date: date = Query(...),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    tags: list[str] | None = Query(default=None, alias="tags"),
    account_type: AccountType | None = Query(default=None, alias="account_type"),
    *,
    db: DbSession,
    user_id: CurrentUserId,
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
    await db.commit()
    return IncomeStatementResponse.model_validate(report)


@router.get("/cash-flow", response_model=CashFlowResponse)
async def cash_flow(
    start_date: date = Query(...),
    end_date: date = Query(...),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    *,
    db: DbSession,
    user_id: CurrentUserId,
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
    await db.commit()
    return CashFlowResponse.model_validate(report)


@router.get("/trend", response_model=AccountTrendResponse)
async def account_trend(
    account_id: UUID = Query(...),
    period: TrendPeriod = Query(default=TrendPeriod.MONTHLY),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    *,
    db: DbSession,
    user_id: CurrentUserId,
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
    await db.commit()
    return AccountTrendResponse.model_validate(report)


@router.get("/net-worth/timeseries", response_model=NetWorthTimeSeriesResponse)
async def net_worth_timeseries(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    granularity: NetWorthGranularity = Query(default=NetWorthGranularity.MONTHLY),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    *,
    db: DbSession,
    user_id: CurrentUserId,
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
    await db.commit()
    return NetWorthTimeSeriesResponse.model_validate(report)


@router.get("/net-worth/allocation", response_model=NetWorthAllocationResponse)
async def net_worth_allocation(
    as_of_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    include_restricted: bool = Query(default=DEFAULT_INCLUDE_RESTRICTED),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> NetWorthAllocationResponse:
    """Get signed net-worth allocation grouped by asset class, liquidity, and source currency."""
    report_date = as_of_date or date.today()
    try:
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=report_date)
        report = await get_net_worth_allocation_schedule(
            db,
            user_id,
            as_of_date=report_date,
            currency=currency,
            include_restricted=include_restricted,
        )
    except ReportError as exc:
        logger.warning(
            "Net worth allocation generation failed",
            as_of_date=str(report_date),
            currency=currency,
            include_restricted=include_restricted,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)
    await db.commit()
    return NetWorthAllocationResponse.model_validate(report)


@router.get("/breakdown", response_model=CategoryBreakdownResponse)
async def category_breakdown(
    breakdown_type: BreakdownType = Query(..., alias="type"),
    period: BreakdownPeriod = Query(default=BreakdownPeriod.MONTHLY),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    *,
    db: DbSession,
    user_id: CurrentUserId,
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
    await db.commit()
    return CategoryBreakdownResponse.model_validate(report)


@router.get("/export")
async def export_report(
    report_type: ExportReportType = Query(...),
    format: ExportFormat = Query(default=ExportFormat.CSV),
    as_of_date: date | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    include_restricted: bool = Query(default=False),
    framework_id: PersonalReportingFrameworkId | None = Query(default=None),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> StreamingResponse:
    """Export reports in CSV format."""
    output = StringIO()
    writer = csv.writer(output)

    try:
        if report_type == ExportReportType.BALANCE_SHEET:
            report_date = as_of_date or date.today()
            await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=report_date)
            balance_sheet_report = cast(
                dict[str, Any],
                await generate_balance_sheet(
                    db,
                    user_id,
                    as_of_date=report_date,
                    currency=currency,
                    include_restricted=include_restricted,
                ),
            )
            writer.writerow(["section", "account", "amount", "currency"])
            for section, balance_lines in (
                ("Assets", balance_sheet_report["assets"]),
                ("Liabilities", balance_sheet_report["liabilities"]),
                ("Equity", balance_sheet_report["equity"]),
            ):
                for balance_line in balance_lines:
                    writer.writerow(
                        [section, balance_line["name"], balance_line["amount"], balance_sheet_report["currency"]]
                    )
            writer.writerow(
                ["Total Assets", "", balance_sheet_report["total_assets"], balance_sheet_report["currency"]]
            )
            writer.writerow(
                [
                    "Total Liabilities",
                    "",
                    balance_sheet_report["total_liabilities"],
                    balance_sheet_report["currency"],
                ]
            )
            writer.writerow(
                ["Total Equity", "", balance_sheet_report["total_equity"], balance_sheet_report["currency"]]
            )
            filename = f"balance-sheet-{balance_sheet_report['as_of_date']}.csv"
        elif report_type == ExportReportType.INCOME_STATEMENT:
            if not start_date or not end_date:
                raise_bad_request("start_date and end_date are required for income statement export")
            await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=end_date)
            income_statement_report = cast(
                dict[str, Any],
                await generate_income_statement(
                    db,
                    user_id,
                    start_date=start_date,
                    end_date=end_date,
                    currency=currency,
                ),
            )
            writer.writerow(["section", "account", "amount", "currency"])
            for section, income_lines in (
                ("Income", income_statement_report["income"]),
                ("Expenses", income_statement_report["expenses"]),
            ):
                for income_line in income_lines:
                    writer.writerow(
                        [section, income_line["name"], income_line["amount"], income_statement_report["currency"]]
                    )
            writer.writerow(
                ["Total Income", "", income_statement_report["total_income"], income_statement_report["currency"]]
            )
            writer.writerow(
                [
                    "Total Expenses",
                    "",
                    income_statement_report["total_expenses"],
                    income_statement_report["currency"],
                ]
            )
            writer.writerow(
                ["Net Income", "", income_statement_report["net_income"], income_statement_report["currency"]]
            )
            filename = f"income-statement-{start_date}-to-{end_date}.csv"
        elif report_type == ExportReportType.CASH_FLOW:
            if not start_date or not end_date:
                raise_bad_request("start_date and end_date are required for cash flow export")
            await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=end_date)
            cash_flow_report = cast(
                dict[str, Any],
                await generate_cash_flow(
                    db,
                    user_id,
                    start_date=start_date,
                    end_date=end_date,
                    currency=currency,
                ),
            )
            writer.writerow(["section", "account", "amount", "currency", "description"])
            for section, cash_flow_lines in (
                ("Operating", cash_flow_report["operating"]),
                ("Investing", cash_flow_report["investing"]),
                ("Financing", cash_flow_report["financing"]),
            ):
                for cash_flow_line in cash_flow_lines:
                    writer.writerow(
                        [
                            section,
                            cash_flow_line["subcategory"],
                            cash_flow_line["amount"],
                            cash_flow_report["currency"],
                            cash_flow_line.get("description") or "",
                        ]
                    )
            summary = cash_flow_report["summary"]
            writer.writerow(
                ["Operating Activities", "", summary["operating_activities"], cash_flow_report["currency"], ""]
            )
            writer.writerow(
                ["Investing Activities", "", summary["investing_activities"], cash_flow_report["currency"], ""]
            )
            writer.writerow(
                ["Financing Activities", "", summary["financing_activities"], cash_flow_report["currency"], ""]
            )
            writer.writerow(["Net Cash Flow", "", summary["net_cash_flow"], cash_flow_report["currency"], ""])
            writer.writerow(["Beginning Cash", "", summary["beginning_cash"], cash_flow_report["currency"], ""])
            writer.writerow(["Ending Cash", "", summary["ending_cash"], cash_flow_report["currency"], ""])
            filename = f"cash-flow-{start_date}-to-{end_date}.csv"
        else:  # pragma: no cover - FastAPI enum validation rejects unsupported values first.
            raise_bad_request("Unsupported report type")
    except ReportError as exc:
        logger.warning(
            "Report export failed",
            report_type=report_type.value,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)

    await db.commit()
    content = output.getvalue()
    output.close()
    envelope = ExportStreamEnvelope(media_type=ExportStreamMediaType.CSV, filename=filename)
    return StreamingResponse(
        StringIO(content),
        media_type=envelope.media_type.value,
        headers=envelope.to_headers(),
    )


@router.get("/{report_type}/snapshots", response_model=list[ReportSnapshotSummary])
async def list_report_snapshots(
    report_type: SnapshotReportType,
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> list[ReportSnapshotSummary]:
    """List available report snapshots for a given report type.

    AC18.4.2: ReportSnapshot (Layer 4) is queryable via API. ``report_type`` is
    typed as the snapshot enum so an unknown value is rejected with 422 at the
    boundary (#1008) instead of silently returning an empty list.
    """
    from sqlalchemy import select as sa_select

    stmt = (
        sa_select(ReportSnapshot)
        .where(ReportSnapshot.report_type == report_type)
        .where(ReportSnapshot.user_id == user_id)
        .order_by(ReportSnapshot.created_at.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    snapshots = result.scalars().all()

    return [ReportSnapshotSummary.model_validate(s) for s in snapshots]
