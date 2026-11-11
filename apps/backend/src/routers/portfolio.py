"""Portfolio management API router."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.audit import Ratio, to_money
from src.deps import CurrentUserId, DbSession
from src.extraction import BrokeragePositionImportService, ManagedPosition, PositionStatus
from src.observability import get_logger
from src.portfolio import (
    AssetNotFoundError,
    InsufficientDataError,
    InvestmentAccountingService,
    InvestmentAccountingValidationError,
    InvestmentTransaction,
    InvestmentTransactionType,
    PerformanceError,
    PortfolioNotFoundError,
    PositionServiceError,
    build_investment_performance_report_schedule,
    calculate_money_weighted_return,
    calculate_time_weighted_return,
    calculate_xirr,
    get_asset_class_allocation as asset_class_allocation_breakdowns,
    get_geography_allocation as geography_allocation_breakdowns,
    get_sector_allocation as sector_allocation_breakdowns,
    portfolio_service,
)
from src.pricing import PricingError
from src.schemas.portfolio import (
    BrokerageImportRequest,
    BrokerageImportResponse,
    CostBasisMethodUpdateRequest,
    CostBasisMethodUpdateResponse,
    DividendEventResponse,
    HoldingsListResponse,
    InvestmentPerformanceReportScheduleResponse,
    PerformanceMetricsResponse,
    PortfolioSummaryDashboardResponse,
    PriceUpdateBatchResponse,
    PriceUpdateRequest,
    RealizedLotResponse,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])
logger = get_logger(__name__)

_DEFAULT_LIST_LIMIT = 100
_MAX_LIST_LIMIT = 500

_portfolio_service = portfolio_service
_brokerage_import_service = BrokeragePositionImportService()
_investment_accounting_service = InvestmentAccountingService()


def _canonical_percent(value: Decimal) -> Decimal:
    ratio = Ratio.from_percent(value)
    return ratio.to_percent()


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


async def _paged_allocation(fn, *, db: DbSession, user_id: UUID, as_of_date: date | None, limit: int, offset: int):
    breakdowns = await fn(db=db, user_id=user_id, as_of_date=as_of_date or date.today())
    return [AllocationBreakdownResponse(**b.to_dict()) for b in list(breakdowns)[offset : offset + limit]]


class AllocationBreakdownResponse(BaseModel):
    category: str
    value: Decimal = Field(decimal_places=2)
    percentage: Decimal = Field(decimal_places=2)
    count: int


class PriceUpdateBatchRequest(BaseModel):
    updates: list[PriceUpdateRequest]


class DividendCreateRequest(BaseModel):
    payment_date: date
    amount: Decimal = Field(decimal_places=2, gt=0)
    currency: str = Field(min_length=3, max_length=3)
    dividend_type: str = "ordinary"
    notes: str | None = None
    cash_account_id: UUID | None = None
    dividend_income_account_id: UUID | None = None
    withholding_tax: Decimal = Field(default=Decimal("0.00"), decimal_places=2, ge=0)
    withholding_tax_account_id: UUID | None = None


@router.post("/brokerage/import", response_model=BrokerageImportResponse, status_code=status.HTTP_200_OK)
async def import_brokerage_positions(
    request: BrokerageImportRequest, db: DbSession, user_id: CurrentUserId
) -> BrokerageImportResponse:
    """Import parsed brokerage holdings into AtomicPosition and reconcile ManagedPosition."""
    try:
        result = await _brokerage_import_service.import_positions(
            db,
            user_id=user_id,
            payload=request.payload,
            filename=request.filename,
            source_document_id=request.source_document_id,
        )
        await db.commit()
    except PositionServiceError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return BrokerageImportResponse(**result.__dict__)


@router.get("/holdings", response_model=HoldingsListResponse)
async def get_holdings(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
    include_disposed: bool = Query(False, description="Include disposed positions"),
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> HoldingsListResponse:
    """Get portfolio holdings with P&L."""
    warnings: list[dict[str, str]] = []
    try:
        holdings = list(
            await _portfolio_service.get_holdings(
                db=db, user_id=user_id, as_of_date=as_of_date, include_disposed=include_disposed, warnings=warnings
            )
        )
    except (PortfolioNotFoundError, AssetNotFoundError):
        return HoldingsListResponse(items=[], total=0, warnings=warnings)
    return HoldingsListResponse(items=holdings[offset : offset + limit], total=len(holdings), warnings=warnings)


@router.get("/summary", response_model=PortfolioSummaryDashboardResponse)
async def get_portfolio_summary(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
) -> PortfolioSummaryDashboardResponse:
    """Get portfolio summary with YTD realized P&L and dividend income."""
    try:
        return await _portfolio_service.get_portfolio_summary_dashboard(db=db, user_id=user_id, as_of_date=as_of_date)
    except PricingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/{ticker}/dividends", response_model=list[DividendEventResponse])
async def get_holding_dividends(
    ticker: str,
    db: DbSession,
    user_id: CurrentUserId,
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[DividendEventResponse]:
    """List dividend events for a holding ticker."""
    dividends = await _investment_accounting_service.list_holding_dividends(
        db, user_id=user_id, ticker=ticker, limit=limit, offset=offset
    )
    return [_dividend_response(d) for d in dividends]


@router.post("/{ticker}/dividends", response_model=DividendEventResponse, status_code=status.HTTP_201_CREATED)
async def create_holding_dividend(
    ticker: str,
    request: DividendCreateRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> DividendEventResponse:
    """Record dividend income for an existing current-user holding."""
    try:
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
        )
    except PortfolioNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (InvestmentAccountingValidationError, PricingError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    entry_id = getattr(dividend, "journal_entry_id", None)
    await db.commit()
    await db.refresh(dividend)
    return _dividend_response(dividend, journal_entry_id=entry_id)


@router.get("/{ticker}/realized", response_model=list[RealizedLotResponse])
async def get_holding_realized_lots(
    ticker: str,
    db: DbSession,
    user_id: CurrentUserId,
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[RealizedLotResponse]:
    """List lot-level realized P&L rows for a holding ticker."""
    rows = (
        await db.execute(
            select(InvestmentTransaction, ManagedPosition)
            .outerjoin(ManagedPosition, InvestmentTransaction.position_id == ManagedPosition.id)
            .where(
                InvestmentTransaction.user_id == user_id,
                InvestmentTransaction.transaction_type == InvestmentTransactionType.SELL,
                InvestmentTransaction.asset_identifier == ticker,
            )
            .order_by(InvestmentTransaction.transaction_date.desc(), InvestmentTransaction.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
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
    db: DbSession,
    user_id: CurrentUserId,
) -> CostBasisMethodUpdateResponse:
    """Persist cost-basis method for all active positions matching a holding ticker."""
    positions = list(
        (
            await db.execute(
                select(ManagedPosition).where(
                    ManagedPosition.user_id == user_id,
                    ManagedPosition.asset_identifier == ticker,
                    ManagedPosition.status == PositionStatus.ACTIVE,
                )
            )
        )
        .scalars()
        .all()
    )
    if not positions:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")
    for p in positions:
        p.cost_basis_method = request.cost_basis_method
    await db.commit()
    return CostBasisMethodUpdateResponse(updated_count=len(positions), cost_basis_method=request.cost_basis_method)


@router.get("/performance", response_model=PerformanceMetricsResponse)
async def get_performance(
    db: DbSession,
    user_id: CurrentUserId,
    period_start: date | None = Query(None, description="Period start date (for TWR)"),
    period_end: date | None = Query(None, description="Period end date (for TWR, default: today)"),
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
) -> PerformanceMetricsResponse:
    """Calculate portfolio performance metrics (XIRR, TWR, MWR)."""
    as_of = as_of_date or date.today()
    p_end = period_end or date.today()
    reasons: dict[str, str] = {}

    async def _eval_metric(key: str, coro) -> Decimal | None:
        try:
            return _canonical_percent(await coro)
        except InsufficientDataError as exc:
            reasons[key] = str(exc)
            return None
        except (PerformanceError, PricingError) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    xirr = await _eval_metric("xirr", calculate_xirr(db=db, user_id=user_id, as_of_date=as_of))
    if period_start:
        if await db.scalar(select(ManagedPosition.id).where(ManagedPosition.user_id == user_id).limit(1)) is None:
            twr = None
            reasons["time_weighted_return"] = "No positions found for time-weighted return calculation"
        else:
            twr = await _eval_metric(
                "time_weighted_return",
                calculate_time_weighted_return(db=db, user_id=user_id, period_start=period_start, period_end=p_end),
            )
    else:
        twr = None
        reasons["time_weighted_return"] = "period_start is required for time-weighted return calculation"
    mwr = await _eval_metric(
        "money_weighted_return", calculate_money_weighted_return(db=db, user_id=user_id, as_of_date=as_of)
    )

    return PerformanceMetricsResponse(
        xirr=xirr, time_weighted_return=twr, money_weighted_return=mwr, unavailable_reasons=reasons
    )


@router.get("/performance/report-schedule", response_model=InvestmentPerformanceReportScheduleResponse)
async def get_investment_performance_report_schedule(
    db: DbSession,
    user_id: CurrentUserId,
    period_start: date | None = Query(None, description="Report period start date (default: Jan 1 of period end year)"),
    period_end: date | None = Query(None, description="Report period end date (default: today)"),
    as_of_date: date | None = Query(None, description="Valuation date (default: period_end)"),
    currency: str = Query(default="SGD", min_length=3, max_length=3),
) -> InvestmentPerformanceReportScheduleResponse:
    """Build the report-ready investment performance schedule."""
    period_end = period_end or date.today()
    period_start = period_start or date(period_end.year, 1, 1)
    as_of_date = as_of_date or period_end
    if period_start > period_end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="period_start must be <= period_end"
        )
    if as_of_date < period_end:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="as_of_date must be >= period_end")
    currency = currency.strip().upper()
    if currency != "SGD":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Investment performance report schedule currently supports SGD presentation currency",
        )
    try:
        return await build_investment_performance_report_schedule(
            db, user_id, period_start=period_start, period_end=period_end, as_of_date=as_of_date, currency=currency
        )
    except PricingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/allocation/sector", response_model=list[AllocationBreakdownResponse])
async def get_sector_allocation(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[AllocationBreakdownResponse]:
    """Get sector allocation breakdown."""
    return await _paged_allocation(
        sector_allocation_breakdowns, db=db, user_id=user_id, as_of_date=as_of_date, limit=limit, offset=offset
    )


@router.get("/allocation/geography", response_model=list[AllocationBreakdownResponse])
async def get_geography_allocation(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[AllocationBreakdownResponse]:
    """Get geography allocation breakdown."""
    return await _paged_allocation(
        geography_allocation_breakdowns, db=db, user_id=user_id, as_of_date=as_of_date, limit=limit, offset=offset
    )


@router.get("/allocation/asset-class", response_model=list[AllocationBreakdownResponse])
async def get_asset_class_allocation(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date | None = Query(None, description="Calculate as of this date (default: today)"),
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT, description="Maximum items to return"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> list[AllocationBreakdownResponse]:
    """Get asset class allocation breakdown."""
    return await _paged_allocation(
        asset_class_allocation_breakdowns, db=db, user_id=user_id, as_of_date=as_of_date, limit=limit, offset=offset
    )


@router.post("/prices/update", response_model=PriceUpdateBatchResponse, status_code=status.HTTP_200_OK)
async def update_prices(
    db: DbSession, user_id: CurrentUserId, request: PriceUpdateBatchRequest
) -> PriceUpdateBatchResponse:
    """Update market prices manually (batch)."""
    results = await _portfolio_service.update_market_prices(db=db, user_id=user_id, updates=request.updates)
    await db.commit()
    return PriceUpdateBatchResponse(updated_count=len(results), results=results)
