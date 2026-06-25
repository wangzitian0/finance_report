"""Financial reporting API router."""

from __future__ import annotations

import asyncio
import csv
import json
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from io import StringIO
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, union

from src.analytics import track as _track_analytics
from src.config import settings
from src.constants.report_package import (
    PERSONAL_REPORT_PACKAGE_CONTRACT,
    PERSONAL_REPORT_PACKAGE_NOTES,
)
from src.deps import CurrentUserId, DbSession, Pagination
from src.logger import get_logger
from src.models import (
    Account,
    AccountType,
    FxRate,
)
from src.models.layer4 import ReportSnapshot, ReportType as SnapshotReportType
from src.schemas import (
    AccountLineageResponse,
    AccountTrendResponse,
    AnnualizedIncomeScheduleResponse,
    BalanceSheetResponse,
    BreakdownPeriod,
    BreakdownType,
    CashFlowResponse,
    CategoryBreakdownResponse,
    FrameworkPolicyResult,
    IncomeStatementResponse,
    NetWorthAllocationResponse,
    NetWorthGranularity,
    NetWorthTimeSeriesResponse,
    PersonalReportingFrameworkId,
    PersonalReportPackageContractResponse,
    PersonalReportPackageGenerateRequest,
    PersonalReportPackageNotesResponse,
    PersonalReportPackageReadinessResponse,
    PersonalReportPackageSnapshotResponse,
    PersonalReportPackageSnapshotSummary,
    PersonalReportPackageTraceabilityResponse,
    ReportSnapshotSummary,
    TrendPeriod,
)
from src.schemas.streaming import ExportStreamEnvelope, ExportStreamMediaType
from src.services.annualized_income import generate_annualized_income_schedule
from src.services.confidence_metric import ConfidenceMetricService
from src.services.framework_policy import derive_user_framework_policy_result
from src.services.market_data import ensure_market_data_fresh
from src.services.performance_report import (
    build_investment_performance_report_schedule,
)
from src.services.report_package import (
    jsonable as _jsonable,
    package_currency as _package_currency,
    package_dates as _package_dates,
    package_snapshot_csv as _package_snapshot_csv,
    package_snapshot_response as _package_snapshot_response,
    package_snapshot_status as _package_snapshot_status,
    package_snapshot_summary as _package_snapshot_summary,
)
from src.services.report_readiness import get_personal_report_package_readiness
from src.services.report_traceability import (
    build_personal_report_package_traceability_payload,
)
from src.services.reporting import (
    ReportError,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
    get_account_lineage,
    get_account_trend,
    get_category_breakdown,
    get_net_worth_allocation_schedule,
    get_net_worth_timeseries,
)
from src.services.reporting_snapshot import ReportingSnapshotService
from src.utils import raise_bad_request, raise_not_found

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
        await ensure_market_data_fresh(
            db,
            user_id=user_id,
            end_date=end_date,
            include_default_fx=False,
            extra_fx_pairs=_target_currency_pair(currency) if has_report_subjects is not None else [],
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


class PackageSnapshotExportFormat(str, Enum):
    """Supported saved package snapshot export formats."""

    JSON = "json"
    CSV = "csv"


class ExportReportType(str, Enum):
    """Supported report types for export."""

    BALANCE_SHEET = "balance-sheet"
    INCOME_STATEMENT = "income-statement"
    CASH_FLOW = "cash-flow"
    PACKAGE = "package"


@router.get("/package/contract", response_model=PersonalReportPackageContractResponse)
def personal_report_package_contract(
    framework_id: PersonalReportingFrameworkId | None = None,
) -> PersonalReportPackageContractResponse:
    """Return the stable package-level API/export contract."""
    payload = deepcopy(PERSONAL_REPORT_PACKAGE_CONTRACT)
    payload["selected_framework_id"] = framework_id.value if framework_id is not None else None
    return PersonalReportPackageContractResponse(**payload)


@router.get("/package/readiness", response_model=PersonalReportPackageReadinessResponse)
async def personal_report_package_readiness(
    framework_id: PersonalReportingFrameworkId | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    as_of_date: date | None = None,
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> PersonalReportPackageReadinessResponse:
    """Return deterministic readiness and blocker state for the personal package."""
    payload = await get_personal_report_package_readiness(
        db,
        user_id,
        framework_id=framework_id,
        report_period_start=start_date,
        report_period_end=end_date,
        as_of_date=as_of_date,
    )
    return PersonalReportPackageReadinessResponse(**payload)


@router.get("/package/framework-policy", response_model=FrameworkPolicyResult)
async def personal_report_package_framework_policy(
    framework_id: PersonalReportingFrameworkId = PersonalReportingFrameworkId.US_GAAP_LIKE,
    start_date: date | None = None,
    end_date: date | None = None,
    as_of_date: date | None = None,
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> FrameworkPolicyResult:
    """Return the selected framework policy result consumed by package assembly."""
    report_as_of = as_of_date or end_date or date.today()
    report_end = end_date or report_as_of
    report_start = start_date or report_end - timedelta(days=365)
    return await derive_user_framework_policy_result(
        db,
        user_id,
        framework_id=framework_id,
        report_period_start=report_start,
        report_period_end=report_end,
        as_of_date=report_as_of,
    )


@router.get("/package/notes", response_model=PersonalReportPackageNotesResponse)
def personal_report_package_notes() -> PersonalReportPackageNotesResponse:
    """Return package-level notes and disclosures."""
    return PersonalReportPackageNotesResponse(**PERSONAL_REPORT_PACKAGE_NOTES)


@router.get("/package/traceability", response_model=PersonalReportPackageTraceabilityResponse)
async def personal_report_package_traceability(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    as_of_date: date | None = Query(default=None),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> PersonalReportPackageTraceabilityResponse:
    """Return the package-level source-ledger-report traceability appendix."""
    payload = await build_personal_report_package_traceability_payload(
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
        db=db,
        user_id=user_id,
    )
    return PersonalReportPackageTraceabilityResponse(**payload)


@router.get("/package/annualized-income-schedule", response_model=AnnualizedIncomeScheduleResponse)
async def annualized_income_schedule(
    as_of_date: date | None = Query(default=None),
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> AnnualizedIncomeScheduleResponse:
    """Return report-ready annualized income and restricted compensation schedule."""
    return await generate_annualized_income_schedule(db, user_id, as_of_date=as_of_date)


async def _personal_report_package_section_payloads(
    *,
    db: DbSession,
    user_id: CurrentUserId,
    start_date: date,
    end_date: date,
    as_of_date: date,
    currency: str,
    include_restricted: bool = False,
) -> dict[str, Any]:
    balance_sheet_payload = await generate_balance_sheet(
        db,
        user_id,
        as_of_date=as_of_date,
        currency=currency,
        include_restricted=include_restricted,
    )
    income_statement_payload = await generate_income_statement(
        db,
        user_id,
        start_date=start_date,
        end_date=end_date,
        currency=currency,
    )
    cash_flow_payload = await generate_cash_flow(
        db,
        user_id,
        start_date=start_date,
        end_date=end_date,
        currency=currency,
    )
    # #1097 (AC25.5.1): call the service directly instead of importing the
    # portfolio router handler. The package path already passes validated,
    # concrete dates and a normalized (uppercased) currency, so the router
    # handler's input-defaulting/validation is moot here and behavior is
    # preserved by invoking the same underlying service.
    investment_performance_payload = await build_investment_performance_report_schedule(
        db,
        user_id,
        period_start=start_date,
        period_end=end_date,
        as_of_date=as_of_date,
        currency=currency,
    )
    annualized_payload = await annualized_income_schedule(
        as_of_date=as_of_date,
        db=db,
        user_id=user_id,
    )
    traceability_payload = await personal_report_package_traceability(
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
        db=db,
        user_id=user_id,
    )
    return {
        "balance_sheet": _jsonable(balance_sheet_payload),
        "income_statement": _jsonable(income_statement_payload),
        "cash_flow": _jsonable(cash_flow_payload),
        "investment_performance": _jsonable(investment_performance_payload),
        "annualized_income_long_term": _jsonable(annualized_payload),
        "notes": personal_report_package_notes().model_dump(mode="json"),
        "traceability_appendix": _jsonable(traceability_payload),
    }


async def _build_personal_report_package_snapshot_data(
    *,
    db: DbSession,
    user_id: CurrentUserId,
    framework_id: PersonalReportingFrameworkId,
    start_date: date,
    end_date: date,
    as_of_date: date,
    currency: str,
    include_restricted: bool = False,
) -> dict[str, Any]:
    contract = personal_report_package_contract(framework_id).model_dump(mode="json")
    readiness = await get_personal_report_package_readiness(
        db,
        user_id,
        framework_id=framework_id,
        report_period_start=start_date,
        report_period_end=end_date,
        as_of_date=as_of_date,
    )
    policy = await derive_user_framework_policy_result(
        db,
        user_id,
        framework_id=framework_id,
        report_period_start=start_date,
        report_period_end=end_date,
        as_of_date=as_of_date,
    )
    section_payloads = await _personal_report_package_section_payloads(
        db=db,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
        currency=currency,
        include_restricted=include_restricted,
    )
    readiness_payload = _jsonable(readiness)
    status_value = _package_snapshot_status(readiness_payload).value
    source_trust_summary = readiness_payload.get("source_trust_summary") or {}
    payload = {
        "package_id": contract["package_id"],
        "version": contract["version"],
        "status": status_value,
        "generated_at": datetime.now(UTC).isoformat(),
        "framework_id": framework_id.value,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "as_of_date": as_of_date.isoformat(),
        "currency": currency,
        "contract": contract,
        "readiness": readiness_payload,
        "source_trust_summary": source_trust_summary,
        "framework_policy": _jsonable(policy),
        "section_payloads": section_payloads,
    }
    return {
        "package_id": contract["package_id"],
        "status": status_value,
        "framework_id": framework_id.value,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "as_of_date": as_of_date.isoformat(),
        "currency": currency,
        "readiness_state": str(readiness_payload.get("state") or "draft"),
        "payload": payload,
    }


@router.post("/package/generate", response_model=PersonalReportPackageSnapshotResponse)
async def generate_personal_report_package_snapshot(
    db: DbSession,
    user_id: CurrentUserId,
    request: PersonalReportPackageGenerateRequest | None = None,
    framework_id: PersonalReportingFrameworkId = PersonalReportingFrameworkId.US_GAAP_LIKE,
    start_date: date | None = None,
    end_date: date | None = None,
    as_of_date: date | None = None,
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    include_restricted: bool = Query(default=False),
) -> PersonalReportPackageSnapshotResponse:
    """Generate and persist an immutable personal report package snapshot."""
    if request is not None:
        framework_id = request.framework_id
        start_date = request.start_date
        end_date = request.end_date
        as_of_date = request.as_of_date
        currency = request.currency
        include_restricted = request.include_restricted
    if not isinstance(currency, str):
        currency = None
    if not isinstance(include_restricted, bool):
        include_restricted = False
    report_start, report_end, report_as_of = _package_dates(
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
    )
    target_currency = _package_currency(currency)
    snapshot_data = await _build_personal_report_package_snapshot_data(
        db=db,
        user_id=user_id,
        framework_id=framework_id,
        start_date=report_start,
        end_date=report_end,
        as_of_date=report_as_of,
        currency=target_currency,
        include_restricted=include_restricted,
    )
    snapshot = await ReportingSnapshotService().create_snapshot(
        db,
        user_id=user_id,
        report_type=SnapshotReportType.PACKAGE,
        start_date=report_start,
        as_of_date=report_as_of,
        rule_version_id=None,
        report_data=snapshot_data,
        ttl_seconds=0,
    )
    # Record a North-Star confidence point per report-package generation (the
    # vision's cadence), so the low-confidence-proportion trend accumulates.
    await ConfidenceMetricService().record_snapshot(db, user_id)
    await db.commit()
    # BE->OpenPanel: server-authoritative `report_generated` (fires even if the
    # browser event is blocked). The official SDK's track() is itself non-blocking
    # (its own daemon send-thread), config-gated + never raises — so calling it
    # inline can't add latency or break report generation, and the handler stays
    # safe to call directly (tests) without a FastAPI BackgroundTasks instance.
    _track_analytics(
        "report_generated",
        {"framework_id": framework_id.value, "currency": target_currency},
    )
    return _package_snapshot_response(snapshot)


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
    return _package_snapshot_response(snapshot)


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
    include_restricted: bool = Query(default=False),
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
    await db.commit()
    return BalanceSheetResponse(**report)


@router.get("/account-lineage", response_model=AccountLineageResponse)
async def account_lineage(
    account_id: UUID = Query(...),
    as_of_date: date | None = Query(default=None),
    start_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: DbSession = None,
    user_id: CurrentUserId = None,
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
    return AccountLineageResponse(**report)


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
    await db.commit()
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
    await db.commit()
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
    await db.commit()
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
    await db.commit()
    return NetWorthTimeSeriesResponse(**report)


@router.get("/net-worth/allocation", response_model=NetWorthAllocationResponse)
async def net_worth_allocation(
    as_of_date: date | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    include_restricted: bool = Query(default=True),
    db: DbSession = None,
    user_id: CurrentUserId = None,
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
    return NetWorthAllocationResponse(**report)


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
    await db.commit()
    return CategoryBreakdownResponse(**report)


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
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> StreamingResponse:
    """Export reports in CSV format."""
    output = StringIO()
    writer = csv.writer(output)

    try:
        if report_type == ExportReportType.BALANCE_SHEET:
            report_date = as_of_date or date.today()
            await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=report_date)
            report = await generate_balance_sheet(
                db,
                user_id,
                as_of_date=report_date,
                currency=currency,
                include_restricted=include_restricted,
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
        elif report_type == ExportReportType.INCOME_STATEMENT:
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
        elif report_type == ExportReportType.CASH_FLOW:
            if not start_date or not end_date:
                raise_bad_request("start_date and end_date are required for cash flow export")
            await _ensure_report_market_data_fresh(db, user_id, currency=currency, end_date=end_date)
            report = await generate_cash_flow(
                db,
                user_id,
                start_date=start_date,
                end_date=end_date,
                currency=currency,
            )
            writer.writerow(["section", "account", "amount", "currency", "description"])
            for section, lines in (
                ("Operating", report["operating"]),
                ("Investing", report["investing"]),
                ("Financing", report["financing"]),
            ):
                for line in lines:
                    writer.writerow(
                        [
                            section,
                            line["subcategory"],
                            line["amount"],
                            report["currency"],
                            line.get("description") or "",
                        ]
                    )
            summary = report["summary"]
            writer.writerow(["Operating Activities", "", summary["operating_activities"], report["currency"], ""])
            writer.writerow(["Investing Activities", "", summary["investing_activities"], report["currency"], ""])
            writer.writerow(["Financing Activities", "", summary["financing_activities"], report["currency"], ""])
            writer.writerow(["Net Cash Flow", "", summary["net_cash_flow"], report["currency"], ""])
            writer.writerow(["Beginning Cash", "", summary["beginning_cash"], report["currency"], ""])
            writer.writerow(["Ending Cash", "", summary["ending_cash"], report["currency"], ""])
            filename = f"cash-flow-{start_date}-to-{end_date}.csv"
        elif report_type == ExportReportType.PACKAGE:
            selected_framework = framework_id or PersonalReportingFrameworkId.US_GAAP_LIKE
            contract = personal_report_package_contract(selected_framework)
            policy = await personal_report_package_framework_policy(
                framework_id=selected_framework,
                start_date=start_date,
                end_date=end_date,
                as_of_date=as_of_date,
                db=db,
                user_id=user_id,
            )
            traceability = await personal_report_package_traceability(
                start_date=start_date,
                end_date=end_date,
                as_of_date=as_of_date,
                db=db,
                user_id=user_id,
            )
            writer.writerow(contract.export_contract.csv_columns)
            evidence_references = sorted(
                {
                    f"{anchor.anchor_type}:{anchor.source_id}"
                    for decision in policy.decisions
                    for anchor in decision.evidence_anchors
                }
                | {f"{anchor.anchor_type}:{anchor.source_id}" for gap in policy.gaps for anchor in gap.evidence_anchors}
            )
            evidence_bundle_references = "|".join(evidence_references)
            for line in traceability.lines:
                writer.writerow(
                    [
                        contract.package_id,
                        line.section_id,
                        line.line_id,
                        line.label,
                        "",
                        currency or settings.base_currency,
                        line.source_state,
                        selected_framework.value,
                        policy.result_id,
                        policy.matrix_version,
                        evidence_bundle_references,
                    ]
                )
            filename = f"personal-report-package-{selected_framework.value}.csv"
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
    db: DbSession = None,
    user_id: CurrentUserId = None,
) -> list[ReportSnapshotSummary]:
    """List available report snapshots for a given report type.

    AC18.4.2: ReportSnapshot (Layer 4) is queryable via API. ``report_type`` is
    typed as the snapshot enum so an unknown value is rejected with 422 at the
    boundary (#1008) instead of silently returning an empty list.
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

    return [ReportSnapshotSummary.model_validate(s) for s in snapshots]
