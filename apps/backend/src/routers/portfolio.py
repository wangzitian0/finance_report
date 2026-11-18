"""Portfolio management API router."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Query, status
from src.audit import to_money
from src.composition import (
    compose_brokerage_import_service,
    import_statement_brokerage_positions,
    refresh_market_data_for_brokerage_import,
)
from src.deps import Ctx, ReadCtx, RequestContext
from src.observability import get_logger
from src.platform import PreconditionFailedError, ResourceNotFoundError
from src.portfolio import (
    AssetNotFoundError,
    InvestmentAccountingService,
    PortfolioNotFoundError,
    PositionService,
    build_investment_performance_report_schedule,
    get_asset_class_allocation as asset_class_allocation_breakdowns,
    get_geography_allocation as geography_allocation_breakdowns,
    get_sector_allocation as sector_allocation_breakdowns,
    portfolio_service,
)
from src.schemas.portfolio import (
    AllocationBreakdownResponse,
    BrokerageImportRequest,
    BrokerageImportResponse,
    CostBasisMethodUpdateRequest,
    CostBasisMethodUpdateResponse,
    DividendCreateRequest,
    DividendEventResponse,
    HoldingsListResponse,
    InvestmentPerformanceReportScheduleResponse,
    PortfolioSummaryDashboardResponse,
    RealizedLotResponse,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])
logger = get_logger(__name__)

_DEFAULT_LIST_LIMIT = 100
_MAX_LIST_LIMIT = 500

_position_service = PositionService()
_brokerage_import_service = compose_brokerage_import_service()
_investment_accounting_service = InvestmentAccountingService()


def _dividend_response(dividend, *, journal_entry_id: UUID | None = None) -> DividendEventResponse:
    return DividendEventResponse(
        id=dividend.id,
        ex_date=dividend.payment_date,
        pay_date=dividend.payment_date,
        amount=dividend.amount,
        currency=dividend.currency,
        reinvested=False,
        journal_entry_id=journal_entry_id
        if journal_entry_id is not None
        else getattr(dividend, "journal_entry_id", None),
    )


async def _paged_allocation(fn, *, ctx: RequestContext, as_of_date: date | None, limit: int, offset: int):
    breakdowns = await fn(
        db=ctx.db, user_id=ctx.user_id, as_of_date=as_of_date or date.today(), base_currency=await ctx.get_base_currency()
    )
    return [AllocationBreakdownResponse(**b.to_dict()) for b in list(breakdowns)[offset : offset + limit]]


@router.post("/brokerage-imports", response_model=BrokerageImportResponse, status_code=status.HTTP_200_OK)
async def import_brokerage_positions(
    request: BrokerageImportRequest, ctx: Ctx
) -> BrokerageImportResponse:
    """Import parsed brokerage holdings from a statement or payload into AtomicPosition and ManagedPosition."""
    db, user_id = ctx.db, ctx.user_id
    if request.statement_id is not None:
        result_payload = await import_statement_brokerage_positions(
            db,
            statement_id=request.statement_id,
            user_id=user_id,
            import_service=_brokerage_import_service,
            audit_logger=logger,
        )
        return BrokerageImportResponse(**result_payload)

    assert request.payload is not None
    result = await _brokerage_import_service.import_positions(
        db,
        user_id=user_id,
        payload=request.payload,
        filename=request.filename,
        source_document_id=request.source_document_id,
    )
    await refresh_market_data_for_brokerage_import(db, user_id=user_id, payload=request.payload)
    return BrokerageImportResponse(**result.__dict__)


@router.get("/holdings", response_model=HoldingsListResponse)
async def get_holdings(
    ctx: ReadCtx,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
    include_disposed: bool = Query(False, description="Include disposed positions"),
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> HoldingsListResponse:
    """Get portfolio holdings with P&L."""
    db, user_id = ctx.db, ctx.user_id
    warnings: list[dict[str, str]] = []
    try:
        holdings = list(
            await portfolio_service.get_holdings(
                db=db,
                user_id=user_id,
                as_of_date=as_of_date,
                include_disposed=include_disposed,
                warnings=warnings,
                base_currency=await ctx.get_base_currency(),
            )
        )
    except (PortfolioNotFoundError, AssetNotFoundError):
        return HoldingsListResponse(items=[], total=0, warnings=warnings)
    return HoldingsListResponse(items=holdings[offset : offset + limit], total=len(holdings), warnings=warnings)


@router.get("/summary", response_model=PortfolioSummaryDashboardResponse)
async def get_portfolio_summary(
    ctx: ReadCtx,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
) -> PortfolioSummaryDashboardResponse:
    """Get portfolio summary with YTD realized P&L and dividend income."""
    return await portfolio_service.get_portfolio_summary_dashboard(
        db=ctx.db, user_id=ctx.user_id, as_of_date=as_of_date, base_currency=await ctx.get_base_currency()
    )


@router.get("/{ticker}/dividends", response_model=list[DividendEventResponse])
async def get_holding_dividends(
    ticker: str,
    ctx: ReadCtx,
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[DividendEventResponse]:
    """List dividend events for a holding ticker."""
    dividends = await _investment_accounting_service.list_holding_dividends(
        ctx.db, user_id=ctx.user_id, ticker=ticker, limit=limit, offset=offset
    )
    return [_dividend_response(d) for d in dividends]


@router.post("/{ticker}/dividends", response_model=DividendEventResponse, status_code=status.HTTP_201_CREATED)
async def create_holding_dividend(
    ticker: str,
    request: DividendCreateRequest,
    ctx: Ctx,
) -> DividendEventResponse:
    """Record dividend income for an existing current-user holding."""
    db, user_id = ctx.db, ctx.user_id
    dividend = await _investment_accounting_service.record_holding_dividend(
        db,
        user_id=user_id,
        ticker=ticker,
        payment_date=request.payment_date,
        amount=request.amount,
        currency=request.currency,
        dividend_type=request.dividend_type,
        withholding_tax=request.withholding_tax,
        cash_account_id=request.cash_account_id,
        dividend_income_account_id=request.dividend_income_account_id,
        withholding_tax_account_id=request.withholding_tax_account_id,
        base_currency=await ctx.get_base_currency(),
    )

    entry_id = getattr(dividend, "journal_entry_id", None)
    await db.flush()
    await db.refresh(dividend)
    return _dividend_response(dividend, journal_entry_id=entry_id)


@router.get("/{ticker}/realized", response_model=list[RealizedLotResponse])
async def get_holding_realized_lots(
    ticker: str,
    ctx: ReadCtx,
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[RealizedLotResponse]:
    """List lot-level realized P&L rows for a holding ticker."""
    rows = await _position_service.list_realized_lots(
        ctx.db, user_id=ctx.user_id, ticker=ticker, limit=limit, offset=offset
    )
    return [
        RealizedLotResponse(
            lot_id=txn.id,
            acquired_date=(acq := pos.acquisition_date if pos else None),
            sold_date=txn.transaction_date,
            quantity=txn.quantity or Decimal("0.000000"),
            basis=to_money(txn.cost_basis or Decimal("0.00")),
            proceeds=to_money(txn.gross_amount - txn.fees),
            gain_loss=to_money(txn.realized_pnl or Decimal("0.00")),
            holding_period=(txn.transaction_date - acq).days if acq else None,
            currency=txn.currency,
        )
        for txn, pos in rows
    ]


@router.patch("/{ticker}", response_model=CostBasisMethodUpdateResponse)
async def update_holding_cost_basis_method(
    ticker: str,
    request: CostBasisMethodUpdateRequest,
    ctx: Ctx,
) -> CostBasisMethodUpdateResponse:
    """Persist cost-basis method for all active positions matching a holding ticker."""
    updated_count = await _position_service.update_cost_basis_method(
        ctx.db, user_id=ctx.user_id, ticker=ticker, cost_basis_method=request.cost_basis_method
    )
    if updated_count == 0:
        raise ResourceNotFoundError("Holding not found")
    await ctx.db.flush()
    return CostBasisMethodUpdateResponse(updated_count=updated_count, cost_basis_method=request.cost_basis_method)


@router.get("/performance/report-schedule", response_model=InvestmentPerformanceReportScheduleResponse)
async def get_investment_performance_report_schedule(
    ctx: ReadCtx,
    period_start: date | None = Query(None, description="Report period start date (default: Jan 1 of period end year)"),
    period_end: date | None = Query(None, description="Report period end date (default: today)"),
    as_of_date: date | None = Query(None, description="Valuation date (default: period_end)"),
    currency: str = Query(default="SGD", min_length=3, max_length=3),
) -> InvestmentPerformanceReportScheduleResponse:
    """Build the report-ready investment performance schedule."""
    db, user_id = ctx.db, ctx.user_id
    period_end = period_end or date.today()
    period_start = period_start or date(period_end.year, 1, 1)
    as_of_date = as_of_date or period_end
    if period_start > period_end:
        raise PreconditionFailedError("period_start must be <= period_end")
    if as_of_date < period_end:
        raise PreconditionFailedError("as_of_date must be >= period_end")
    currency = currency.strip().upper()
    if currency != "SGD":
        raise PreconditionFailedError("Investment performance report schedule currently supports SGD presentation currency")
    return await build_investment_performance_report_schedule(
        db,
        user_id,
        period_start=period_start,
        period_end=period_end,
        as_of_date=as_of_date,
        currency=currency,
        base_currency=await ctx.get_base_currency(),
    )


@router.get("/allocation/sector", response_model=list[AllocationBreakdownResponse])
async def get_sector_allocation(
    ctx: ReadCtx,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[AllocationBreakdownResponse]:
    """Get sector allocation breakdown."""
    return await _paged_allocation(
        sector_allocation_breakdowns, ctx=ctx, as_of_date=as_of_date, limit=limit, offset=offset
    )


@router.get("/allocation/geography", response_model=list[AllocationBreakdownResponse])
async def get_geography_allocation(
    ctx: ReadCtx,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[AllocationBreakdownResponse]:
    """Get geography allocation breakdown."""
    return await _paged_allocation(
        geography_allocation_breakdowns, ctx=ctx, as_of_date=as_of_date, limit=limit, offset=offset
    )


@router.get("/allocation/asset-class", response_model=list[AllocationBreakdownResponse])
async def get_asset_class_allocation(
    ctx: ReadCtx,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[AllocationBreakdownResponse]:
    """Get asset class allocation breakdown."""
    return await _paged_allocation(
        asset_class_allocation_breakdowns, ctx=ctx, as_of_date=as_of_date, limit=limit, offset=offset
    )
