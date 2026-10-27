"""Financial reporting API router."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from io import BytesIO, StringIO
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, union

from src.composition import observed_fx_pairs
from src.config import settings
from src.deps import CurrentUserId, DbSession, Pagination
from src.ledger import Account, AccountType
from src.observability import get_logger, track as _track_analytics
from src.platform import raise_bad_request, raise_not_found
from src.portfolio import active_stock_symbols
from src.pricing import FxRate, ensure_market_data_fresh
from src.reporting import (
    DEFAULT_INCLUDE_RESTRICTED,
    PACKAGE_INCLUDE_RESTRICTED,
    CashFlowLineEventsPage,
    CashFlowPreview,
    EquationDiagnosticResult,
    PackageAssembler,
    PackageDocumentVersionError,
    ReportError,
    ReportingSnapshotService,
    ReportSnapshot,
    ReportType as SnapshotReportType,
    cash_flow_line_events,
    cash_flow_period,
    cash_flow_preview,
    compute_personal_data_quality,
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
    package_preview,
    package_snapshot_csv as _package_snapshot_csv,
    package_snapshot_response as _package_snapshot_response,
    package_snapshot_summary as _package_snapshot_summary,
    report_coverage as _report_coverage,
    run_balance_sheet_diagnostics,
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
    PersonalDataQualityHealthResponse,
    PersonalReportingFrameworkId,
    PersonalReportPackageDocumentLifecycle,
    PersonalReportPackageGenerateRequest,
    PersonalReportPackageLineDetailsPage,
    PersonalReportPackageManifestEntriesPage,
    PersonalReportPackagePreview,
    PersonalReportPackageSnapshotResponse,
    PersonalReportPackageSnapshotSummary,
    PersonalReportPackageTraceabilityAnchorName,
    ReportSnapshotSummary,
    TrendPeriod,
)
from src.schemas.reporting import ReportCoverageResponse
from src.schemas.streaming import ExportStreamEnvelope, ExportStreamMediaType

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
    ZIP = "zip"


class AnnualTaxArchiveRequest(BaseModel):
    """Request payload for annual tax archive ZIP generation."""

    year: int = Field(ge=1900, le=2100)
    currency: str = Field(default="SGD", min_length=3, max_length=3)
    framework_id: PersonalReportingFrameworkId = PersonalReportingFrameworkId.US_GAAP_LIKE


class ExportReportType(str, Enum):
    """Supported report types for export."""

    BALANCE_SHEET = "balance-sheet"
    INCOME_STATEMENT = "income-statement"
    CASH_FLOW = "cash-flow"


async def _package_period(
    db: DbSession,
    user_id: CurrentUserId,
    *,
    start_date: date | None,
    end_date: date | None,
    as_of_date: date | None,
    currency: str | None,
) -> tuple[date, date, date, str]:
    """Resolve the package period and currency, and refresh the market data.

    Each package GET commits at its end, as the other report GETs do. Refreshed prices then
    stay stored, so the preview and the later evidence pages read the same prices. The commit
    comes after the read, so the request keeps one connection.
    """
    report_start, report_end, report_as_of = _package_dates(
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
    )
    target_currency = _package_currency(currency)
    await _ensure_report_market_data_fresh(db, user_id, currency=target_currency, end_date=report_as_of)
    return report_start, report_end, report_as_of, target_currency


@router.get("/package", response_model=PersonalReportPackagePreview)
async def preview_personal_report_package(
    framework_id: PersonalReportingFrameworkId = PersonalReportingFrameworkId.US_GAAP_LIKE,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    as_of_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    include_restricted: bool = Query(default=PACKAGE_INCLUDE_RESTRICTED),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> PersonalReportPackagePreview:
    """Build the typed preview document without persisting a snapshot, and return its bounded projection.

    The traceability details and the input manifest entries load page by page from
    ``GET /reports/package/line-details`` and ``GET /reports/package/manifest-entries`` (#2583).
    """
    report_start, report_end, report_as_of, target_currency = await _package_period(
        db, user_id, start_date=start_date, end_date=end_date, as_of_date=as_of_date, currency=currency
    )
    document = await PackageAssembler().assemble(
        db,
        user_id=user_id,
        framework_id=framework_id,
        start_date=report_start,
        end_date=report_end,
        as_of_date=report_as_of,
        currency=target_currency,
        include_restricted=include_restricted,
    )
    await db.commit()
    return package_preview(document)


@router.get("/package/line-details", response_model=PersonalReportPackageLineDetailsPage)
async def list_personal_report_package_line_details(
    line_id: str = Query(
        min_length=1, max_length=128, description="Traceability line, for example balance_sheet.total_assets"
    ),
    anchor: PersonalReportPackageTraceabilityAnchorName = Query(description="The anchor of the line"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    as_of_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    *,
    db: DbSession,
    user_id: CurrentUserId,
    pagination: Pagination,
) -> PersonalReportPackageLineDetailsPage:
    """Return one page of the details of one traceability line anchor of the preview.

    The details equal the details that a snapshot of the same period stores, in the same order.
    """
    report_start, report_end, report_as_of, target_currency = await _package_period(
        db, user_id, start_date=start_date, end_date=end_date, as_of_date=as_of_date, currency=currency
    )
    details = await PackageAssembler().line_details(
        db,
        user_id=user_id,
        start_date=report_start,
        end_date=report_end,
        as_of_date=report_as_of,
        currency=target_currency,
        line_id=line_id,
        anchor=anchor,
    )
    if details is None:
        raise_not_found("Traceability line")
    await db.commit()
    return PersonalReportPackageLineDetailsPage(
        line_id=line_id,
        anchor=anchor,
        total=len(details),
        limit=pagination.limit,
        offset=pagination.offset,
        details=details[pagination.offset : pagination.offset + pagination.limit],
    )


@router.get("/package/manifest-entries", response_model=PersonalReportPackageManifestEntriesPage)
async def list_personal_report_package_manifest_entries(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    as_of_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    *,
    db: DbSession,
    user_id: CurrentUserId,
    pagination: Pagination,
) -> PersonalReportPackageManifestEntriesPage:
    """Return one page of the input manifest of the preview.

    The entries equal the input manifest that a snapshot of the same period stores, in the same order.
    """
    report_start, report_end, report_as_of, target_currency = await _package_period(
        db, user_id, start_date=start_date, end_date=end_date, as_of_date=as_of_date, currency=currency
    )
    entries = await PackageAssembler().manifest_entries(
        db,
        user_id=user_id,
        start_date=report_start,
        end_date=report_end,
        as_of_date=report_as_of,
        currency=target_currency,
    )
    await db.commit()
    return PersonalReportPackageManifestEntriesPage(
        total=len(entries),
        limit=pagination.limit,
        offset=pagination.offset,
        entries=entries[pagination.offset : pagination.offset + pagination.limit],
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
        include_restricted=(
            PACKAGE_INCLUDE_RESTRICTED if request.include_restricted is None else request.include_restricted
        ),
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
        report_data=document.model_dump(mode="json"),
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


def _csv_val(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _render_balance_sheet_csv(bs: dict[str, Any] | BalanceSheetResponse) -> str:
    output = StringIO()
    writer = csv.writer(output)
    _val = _csv_val

    as_of_date = _val(bs, "as_of_date")
    currency = _val(bs, "currency")
    if as_of_date:
        writer.writerow(["Balance Sheet", str(as_of_date), "", ""])
    writer.writerow(["section", "account", "amount", "currency"])
    for section, lines in (
        ("Assets", _val(bs, "assets", [])),
        ("Liabilities", _val(bs, "liabilities", [])),
        ("Equity", _val(bs, "equity", [])),
    ):
        for line in lines:
            writer.writerow([section, _val(line, "name"), _val(line, "amount"), currency])
    writer.writerow(["Total Assets", "", _val(bs, "total_assets"), currency])
    writer.writerow(["Total Liabilities", "", _val(bs, "total_liabilities"), currency])
    total_equity = _val(bs, "total_equity")
    net_income = _val(bs, "net_income") or Decimal("0.00")
    unrealized_fx = _val(bs, "unrealized_fx_gain_loss") or Decimal("0.00")
    cta_adj = _val(bs, "cta_adjustment") or Decimal("0.00")
    net_worth_adj = _val(bs, "net_worth_adjustment_gain_loss") or Decimal("0.00")
    writer.writerow(["Opening Equity", "", total_equity, currency])
    writer.writerow(["Net Income", "", net_income, currency])
    if unrealized_fx:
        writer.writerow(["Unrealized FX Gain/Loss", "", unrealized_fx, currency])
    if cta_adj:
        writer.writerow(["CTA Adjustment", "", cta_adj, currency])
    if net_worth_adj:
        writer.writerow(["Net Worth Adjustment", "", net_worth_adj, currency])
    ending_equity = (
        Decimal(str(total_equity))
        + Decimal(str(net_income))
        + Decimal(str(unrealized_fx))
        + Decimal(str(cta_adj))
        + Decimal(str(net_worth_adj))
    )
    writer.writerow(["Ending Total Equity", "", ending_equity, currency])
    total_liabilities = _val(bs, "total_liabilities")
    writer.writerow(["Total Liabilities and Equity", "", Decimal(str(total_liabilities)) + ending_equity, currency])
    return output.getvalue()


def _render_income_statement_csv(is_stmt: dict[str, Any] | IncomeStatementResponse) -> str:
    output = StringIO()
    writer = csv.writer(output)
    currency = _csv_val(is_stmt, "currency")
    writer.writerow(["section", "account", "amount", "currency"])
    for section, lines in (
        ("Income", _csv_val(is_stmt, "income", [])),
        ("Expenses", _csv_val(is_stmt, "expenses", [])),
    ):
        for line in lines:
            writer.writerow([section, _csv_val(line, "name"), _csv_val(line, "amount"), currency])
    writer.writerow(["Total Income", "", _csv_val(is_stmt, "total_income"), currency])
    writer.writerow(["Total Expenses", "", _csv_val(is_stmt, "total_expenses"), currency])
    writer.writerow(["Net Income", "", _csv_val(is_stmt, "net_income"), currency])
    return output.getvalue()


def _render_cash_flow_csv(cf: dict[str, Any] | CashFlowResponse) -> str:
    output = StringIO()
    writer = csv.writer(output)
    currency = _csv_val(cf, "currency")
    writer.writerow(["section", "account", "amount", "currency", "description"])
    for section, lines in (
        ("Operating", _csv_val(cf, "operating", [])),
        ("Investing", _csv_val(cf, "investing", [])),
        ("Financing", _csv_val(cf, "financing", [])),
    ):
        for line in lines:
            writer.writerow(
                [
                    section,
                    _csv_val(line, "subcategory"),
                    _csv_val(line, "amount"),
                    currency,
                    _csv_val(line, "description") or "",
                ]
            )
    summary = _csv_val(cf, "summary")
    writer.writerow(["Operating Activities", "", _csv_val(summary, "operating_activities"), currency, ""])
    writer.writerow(["Investing Activities", "", _csv_val(summary, "investing_activities"), currency, ""])
    writer.writerow(["Financing Activities", "", _csv_val(summary, "financing_activities"), currency, ""])
    writer.writerow(["Net Cash Flow", "", _csv_val(summary, "net_cash_flow"), currency, ""])
    proof_reasons = list(_csv_val(cf, "proof_reasons") or [])
    incomplete_coverage = "opening_coverage_starts_after_period" in proof_reasons
    beginning_label = "Known Beginning Cash" if incomplete_coverage else "Beginning Cash"
    writer.writerow([beginning_label, "", _csv_val(summary, "beginning_cash"), currency, ""])
    cash_bridge = _csv_val(cf, "cash_bridge")
    opening_adjustment = (
        _csv_val(cash_bridge, "opening_stock_adjustment", Decimal("0")) if cash_bridge else Decimal("0")
    )
    if opening_adjustment:
        writer.writerow(
            [
                "Opening balance adjustment",
                "",
                opening_adjustment,
                currency,
                "Opening balance recorded after the selected period begins",
            ]
        )
    writer.writerow(["Ending Cash", "", _csv_val(summary, "ending_cash"), currency, ""])
    if _csv_val(cf, "proof_state") == "unproven":
        writer.writerow(["Verification", "", "", "", "unproven: " + ", ".join(str(r) for r in proof_reasons)])
    return output.getvalue()


def _package_snapshot_zip(snapshot: PersonalReportPackageSnapshotResponse) -> bytes:
    sections = snapshot.document.sections
    files_data = [
        ("balance_sheet.csv", _render_balance_sheet_csv(sections.balance_sheet)),
        ("income_statement.csv", _render_income_statement_csv(sections.income_statement)),
        ("cash_flow.csv", _render_cash_flow_csv(sections.cash_flow)),
    ]
    file_entries = []
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for filename, content in files_data:
            data = content.encode("utf-8")
            zf.writestr(filename, data)
            file_entries.append(
                {
                    "filename": filename,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size_bytes": len(data),
                }
            )
        manifest = {
            "package_id": str(snapshot.id),
            "reporting_currency": snapshot.currency,
            "as_of_date": str(snapshot.as_of_date),
            "tax_year": snapshot.as_of_date.year,
            "files": file_entries,
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"))
    return buffer.getvalue()


@router.get("/package/snapshots/{snapshot_id}/export")
async def export_personal_report_package_snapshot(
    snapshot_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
    format: PackageSnapshotExportFormat = Query(default=PackageSnapshotExportFormat.CSV),
) -> StreamingResponse:
    """Export a saved package snapshot as JSON, CSV, or ZIP."""
    snapshot = await get_personal_report_package_snapshot(snapshot_id=snapshot_id, db=db, user_id=user_id)
    stem = f"personal-report-package-{snapshot.framework_id.value}-{snapshot.as_of_date}-{snapshot.id}"
    if format == PackageSnapshotExportFormat.ZIP:
        zip_bytes = _package_snapshot_zip(snapshot)
        filename = f"{stem}.zip"
        return StreamingResponse(
            BytesIO(zip_bytes),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(zip_bytes)),
            },
        )
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


@router.post("/package/annual-archive")
async def export_annual_tax_archive(
    request: AnnualTaxArchiveRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> StreamingResponse:
    """Generate and stream an annual tax & audit package archive ZIP."""
    start_date = date(request.year, 1, 1)
    end_date = date(request.year, 12, 31)
    target_currency = _package_currency(request.currency)
    await _ensure_report_market_data_fresh(db, user_id, currency=target_currency, end_date=end_date)
    snapshot = await generate_personal_report_package_snapshot(
        db=db,
        user_id=user_id,
        request=PersonalReportPackageGenerateRequest(
            framework_id=request.framework_id,
            start_date=start_date,
            end_date=end_date,
            as_of_date=end_date,
            currency=target_currency,
        ),
    )
    zip_bytes = _package_snapshot_zip(snapshot)
    filename = f"annual-tax-archive-{request.year}.zip"
    return StreamingResponse(
        BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(zip_bytes)),
        },
    )


@router.get("/coverage", response_model=ReportCoverageResponse)
async def report_coverage(
    as_of_date: date | None = Query(default=None),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> ReportCoverageResponse:
    """Return the first day that the default report view can start without a cash coverage gap.

    Home and `/reports` bound their default view by it and name the accounts that set it (#2646).
    The workflow readiness uses the same bound. ``as_of_date`` is the end of the shown period.
    """
    resolved = as_of_date or date.today()
    coverage = await _report_coverage(db, user_id=user_id, as_of=resolved)
    return ReportCoverageResponse(
        as_of_date=resolved,
        coverage_start=coverage.start,
        limiting_accounts=list(coverage.limiting_account_names),
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


@router.get("/balance-sheet/diagnostics", response_model=EquationDiagnosticResult)
async def balance_sheet_diagnostics(
    as_of_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    include_restricted: bool = Query(default=DEFAULT_INCLUDE_RESTRICTED),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> EquationDiagnosticResult:
    """Diagnose accounting equation out-of-balance root cause (Flow 24)."""
    report_date = as_of_date or date.today()
    try:
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=report_date)
        return await run_balance_sheet_diagnostics(
            db,
            user_id,
            as_of_date=report_date,
            currency=currency,
            include_restricted=include_restricted,
        )
    except ReportError as exc:
        logger.warning(
            "Balance sheet diagnostics failed",
            as_of_date=str(report_date),
            currency=currency,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)


@router.get("/data-quality", response_model=PersonalDataQualityHealthResponse)
async def get_data_quality_health(
    as_of_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> PersonalDataQualityHealthResponse:
    """Return comprehensive financial data quality, invariants, timeline, and action items."""
    report_date = as_of_date or date.today()
    try:
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=report_date)
        return await compute_personal_data_quality(
            db,
            user_id,
            as_of_date=report_date,
            currency=currency,
        )
    except ReportError as exc:
        logger.warning(
            "Data quality evaluation failed",
            as_of_date=str(report_date),
            currency=currency,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)


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
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    tags: list[str] | None = Query(default=None, alias="tags"),
    account_type: AccountType | None = Query(default=None, alias="account_type"),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> IncomeStatementResponse:
    """Get income statement for a period with optional filtering."""
    resolved_end_date = end_date or date.today()
    resolved_start_date = start_date or date(resolved_end_date.year, 1, 1)
    try:
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=resolved_end_date)
        report = await generate_income_statement(
            db,
            user_id,
            start_date=resolved_start_date,
            end_date=resolved_end_date,
            currency=currency,
            tags=tags,
            account_type=account_type,
        )
    except ReportError as exc:
        logger.warning(
            "Income statement generation failed",
            start_date=str(resolved_start_date),
            end_date=str(resolved_end_date),
            currency=currency,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)
    await db.commit()
    return IncomeStatementResponse.model_validate(report)


@router.get("/cash-flow", response_model=CashFlowPreview)
async def cash_flow(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> CashFlowPreview:
    """Get the bounded cash-flow statement; GET /reports/cash-flow/line-events pages the events of a line."""
    resolved_start_date, resolved_end_date = cash_flow_period(start_date, end_date)
    try:
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=resolved_end_date)
        report = await generate_cash_flow(
            db,
            user_id,
            start_date=resolved_start_date,
            end_date=resolved_end_date,
            currency=currency,
        )
    except ReportError as exc:
        logger.warning(
            "Cash flow generation failed",
            start_date=str(resolved_start_date),
            end_date=str(resolved_end_date),
            currency=currency,
            error=str(exc),
        )
        raise_bad_request(str(exc), cause=exc)
    await db.commit()
    return CashFlowPreview.model_validate(cash_flow_preview(report))


@router.get("/cash-flow/line-events", response_model=CashFlowLineEventsPage)
async def list_cash_flow_line_events(
    line_id: str = Query(min_length=1, max_length=64, description="A line_id of GET /reports/cash-flow"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    *,
    db: DbSession,
    user_id: CurrentUserId,
    pagination: Pagination,
) -> CashFlowLineEventsPage:
    """Return one page of the lineage records of one cash-flow line, in document order (#2583)."""
    resolved_start_date, resolved_end_date = cash_flow_period(start_date, end_date)
    try:
        await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=resolved_end_date)
        events = await cash_flow_line_events(
            db, user_id, line_id=line_id, start_date=resolved_start_date, end_date=resolved_end_date, currency=currency
        )
    except ReportError as exc:
        logger.warning("Cash flow line events failed", line_id=line_id, error=str(exc))
        raise_bad_request(str(exc), cause=exc)
    await db.commit()
    if events is None:
        raise_not_found("Cash-flow line")
    page = events[pagination.offset : pagination.offset + pagination.limit]
    bounds = {"line_id": line_id, "total": len(events), "limit": pagination.limit, "offset": pagination.offset}
    return CashFlowLineEventsPage.model_validate({**bounds, "events": page})


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
    include_restricted: bool = Query(default=DEFAULT_INCLUDE_RESTRICTED),
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
            include_restricted=include_restricted,
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
    include_restricted: bool = Query(default=DEFAULT_INCLUDE_RESTRICTED),
    framework_id: PersonalReportingFrameworkId | None = Query(default=None),
    *,
    db: DbSession,
    user_id: CurrentUserId,
) -> StreamingResponse:
    """Export reports in CSV format."""
    _ = (format, framework_id)
    output = StringIO()

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
            output.write(_render_balance_sheet_csv(balance_sheet_report))
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
            output.write(_render_income_statement_csv(income_statement_report))
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
            output.write(_render_cash_flow_csv(cash_flow_report))
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
