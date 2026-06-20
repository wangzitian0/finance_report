"""Investment performance report-schedule assembly (EPIC-005).

Builds the report-ready :class:`InvestmentPerformanceReportScheduleResponse` from
holdings, realized P&L, dividends, allocations, and market-data freshness.
Extracted from the portfolio router so the router stays a thin HTTP layer; the
realized-P&L and dividend aggregation now live on ``PortfolioService`` and are
shared with the portfolio summary endpoint. Raises ``FxRateError`` on conversion
failure (the router maps it to HTTP 422). Behavior unchanged.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from src.deps import CurrentUserId, DbSession
from src.models.layer2 import AtomicPosition
from src.models.layer3 import ManagedPosition, PositionStatus
from src.models.market_data import StockPrice
from src.models.portfolio import MarketDataOverride, PriceSource
from src.money import to_money
from src.ratio import Ratio
from src.schemas.portfolio import (
    HoldingResponse,
    InvestmentPerformanceAllocationRow,
    InvestmentPerformanceDataFreshness,
    InvestmentPerformanceHoldingRow,
    InvestmentPerformanceReportScheduleResponse,
)
from src.services import allocation, performance
from src.services.fx import convert_amount
from src.services.performance import InsufficientDataError, PerformanceError
from src.services.portfolio import AssetNotFoundError, PortfolioNotFoundError, portfolio_service


def _percent(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    percent_ratio = Ratio.from_percent(value)
    return percent_ratio.to_percent()


def _source_document_links(source_documents: object) -> list[str]:
    if isinstance(source_documents, list):
        docs = source_documents
    elif isinstance(source_documents, dict):
        docs = source_documents.get("documents") or source_documents.get("source_documents") or [source_documents]
    else:
        docs = []

    links: list[str] = []
    for doc in docs:
        if isinstance(doc, dict):
            doc_type = doc.get("doc_type") or doc.get("type") or "source"
            doc_id = doc.get("doc_id") or doc.get("id") or doc.get("source_id")
            if doc_id:
                links.append(f"{doc_type}:{doc_id}")
    return links


def _freshness_link(asset_identifier: str, source_kind: str, source_id: object, evidence_date: date) -> str:
    return f"price_source:{source_kind}:{asset_identifier}:{source_id}:{evidence_date.isoformat()}"


async def _report_preparation_holdings(
    db: DbSession,
    user_id: CurrentUserId,
    as_of_date: date,
) -> list[HoldingResponse]:
    """Load current holdings only when post-period manual prices evidence report preparation."""
    override_result = await db.execute(
        select(MarketDataOverride)
        .where(MarketDataOverride.user_id == user_id)
        .where(MarketDataOverride.source == PriceSource.MANUAL)
        .where(MarketDataOverride.price_date > as_of_date)
        .order_by(MarketDataOverride.price_date.desc(), MarketDataOverride.created_at.desc())
    )
    override_assets = {override.asset_identifier for override in override_result.scalars().all()}
    if not override_assets:
        return []

    try:
        current_holdings = await portfolio_service.get_holdings(
            db=db,
            user_id=user_id,
            include_disposed=True,
        )
    except (PortfolioNotFoundError, AssetNotFoundError):
        return []

    return [
        holding
        for holding in current_holdings
        if holding.asset_identifier in override_assets and holding.status == PositionStatus.ACTIVE
    ]


async def build_investment_performance_report_schedule(
    db: DbSession,
    user_id: CurrentUserId,
    *,
    period_start: date,
    period_end: date,
    as_of_date: date,
    currency: str,
) -> InvestmentPerformanceReportScheduleResponse:
    """Assemble the report-ready investment performance schedule (validated inputs)."""
    notes: list[str] = [
        "Cost basis uses the holding-level cost-basis method where available.",
        (
            "Market values use the latest available brokerage or market-data snapshot on or before the as-of date; "
            "report-preparation overrides after the as-of date are disclosed when they evidence active holdings."
        ),
    ]

    used_report_preparation_evidence = False
    try:
        holdings = list(
            await portfolio_service.get_holdings(
                db=db,
                user_id=user_id,
                as_of_date=as_of_date,
                include_disposed=True,
            )
        )
    except (PortfolioNotFoundError, AssetNotFoundError):
        holdings = []

    if not holdings:
        holdings = await _report_preparation_holdings(db=db, user_id=user_id, as_of_date=as_of_date)
        used_report_preparation_evidence = bool(holdings)
        if used_report_preparation_evidence:
            notes.append(
                "No holdings snapshot existed on or before the as-of date; the schedule used active holdings "
                "with post-period manual market-data overrides as report-preparation evidence."
            )
        else:
            notes.append("No portfolio holdings were available for the requested as-of date.")

    asset_identifiers = [holding.asset_identifier for holding in holdings]
    position_by_asset: dict[str, ManagedPosition] = {}
    if asset_identifiers:
        position_result = await db.execute(
            select(ManagedPosition)
            .where(ManagedPosition.user_id == user_id)
            .where(ManagedPosition.asset_identifier.in_(asset_identifiers))
        )
        position_by_asset = {position.asset_identifier: position for position in position_result.scalars().all()}

    async def _schedule_amount(amount: Decimal, source_currency: str, rate_date: date) -> Decimal:
        return await convert_amount(db, amount, source_currency, currency, rate_date, lazy_load=True)

    async def _metric_or_note(metric_name: str, calculation):
        try:
            return await calculation()
        except InsufficientDataError as exc:
            notes.append(f"{metric_name} unavailable: {exc}")
            return None
        except PerformanceError as exc:
            notes.append(f"{metric_name} unavailable: {exc}")
            return None

    xirr = await _metric_or_note(
        "XIRR", lambda: performance.calculate_xirr(db=db, user_id=user_id, as_of_date=as_of_date)
    )
    twr = await _metric_or_note(
        "TWR",
        lambda: performance.calculate_time_weighted_return(
            db=db,
            user_id=user_id,
            period_start=period_start,
            period_end=period_end,
        ),
    )
    mwr = await _metric_or_note(
        "MWR",
        lambda: performance.calculate_money_weighted_return(db=db, user_id=user_id, as_of_date=as_of_date),
    )
    dividend_yield = await _metric_or_note(
        "Dividend yield",
        lambda: performance.calculate_dividend_yield(db=db, user_id=user_id, as_of_date=as_of_date),
    )

    realized_by_asset, realized_source_refs = await portfolio_service.get_realized_pnl_by_asset(
        db, user_id, start_date=period_start, end_date=period_end, target_currency=currency
    )
    source_links: set[str] = {"report_section:investment_performance"}
    source_links.update(realized_source_refs)

    dividend_by_asset = await portfolio_service.get_dividend_income_by_asset(
        db, user_id, start_date=period_start, end_date=period_end, target_currency=currency
    )

    holding_rows: list[InvestmentPerformanceHoldingRow] = []
    for holding in holdings:
        position = position_by_asset.get(holding.asset_identifier)
        if position is None:
            cost_basis = to_money(
                await _schedule_amount(holding.cost_basis, holding.currency, holding.acquisition_date)
            )
        else:
            cost_basis = to_money(
                await _schedule_amount(position.cost_basis, position.currency, position.acquisition_date)
            )
        market_value = to_money(holding.market_value)
        holding_rows.append(
            InvestmentPerformanceHoldingRow(
                asset_identifier=holding.asset_identifier,
                quantity=holding.quantity,
                cost_basis=cost_basis,
                market_value=market_value,
                unrealized_pnl=to_money(market_value - cost_basis),
                realized_pnl=to_money(realized_by_asset.get(holding.asset_identifier, Decimal("0.00"))),
                dividend_income=to_money(dividend_by_asset.get(holding.asset_identifier, Decimal("0.00"))),
                currency=holding.currency,
            )
        )

    allocation_rows: list[InvestmentPerformanceAllocationRow] = []
    for dimension, loader in [
        ("sector", allocation.get_sector_allocation),
        ("geography", allocation.get_geography_allocation),
        ("asset_class", allocation.get_asset_class_allocation),
    ]:
        for row in await loader(db=db, user_id=user_id, as_of_date=as_of_date):
            allocation_rows.append(
                InvestmentPerformanceAllocationRow(
                    dimension=dimension,
                    category=row.category,
                    value=to_money(row.value),
                    percentage=_percent(row.percentage),
                    count=row.count,
                )
            )
    if used_report_preparation_evidence and not allocation_rows and holding_rows:
        total_market_value = sum((row.market_value for row in holding_rows), Decimal("0.00"))
        for dimension, attribute, fallback_category in [
            ("sector", "sector", "Unclassified"),
            ("geography", "geography", "Unclassified"),
            ("asset_class", "asset_type", "Unclassified"),
        ]:
            grouped: dict[str, tuple[Decimal, int]] = {}
            for holding, row in zip(holdings, holding_rows, strict=True):
                category = getattr(holding, attribute) or fallback_category
                current_value, current_count = grouped.get(category, (Decimal("0.00"), 0))
                grouped[category] = (current_value + row.market_value, current_count + 1)
            for category, (value, count) in grouped.items():
                allocation_ratio = Ratio.fraction_or_zero(value, total_market_value)
                allocation_rows.append(
                    InvestmentPerformanceAllocationRow(
                        dimension=dimension,
                        category=category,
                        value=to_money(value),
                        percentage=allocation_ratio.to_percent(),
                        count=count,
                    )
                )
        notes.append("Allocation rows use report-preparation holdings when as-of allocation snapshots are unavailable.")

    latest_atomic_query = select(AtomicPosition).where(AtomicPosition.user_id == user_id)
    if used_report_preparation_evidence and asset_identifiers:
        latest_atomic_query = latest_atomic_query.where(AtomicPosition.asset_identifier.in_(asset_identifiers))
    else:
        latest_atomic_query = latest_atomic_query.where(AtomicPosition.snapshot_date <= as_of_date)
    latest_atomic_result = await db.execute(
        latest_atomic_query.order_by(AtomicPosition.snapshot_date.desc(), AtomicPosition.created_at.desc())
    )
    atomics = list(latest_atomic_result.scalars().all())
    latest_atomic_by_asset: dict[str, AtomicPosition] = {}
    for atomic in atomics:
        latest_atomic_by_asset.setdefault(atomic.asset_identifier, atomic)
        for link in _source_document_links(atomic.source_documents):
            source_links.add(link)

    latest_override_query = (
        select(MarketDataOverride)
        .where(MarketDataOverride.user_id == user_id)
        .where(MarketDataOverride.price_date <= as_of_date)
    )
    latest_override_result = await db.execute(
        latest_override_query.order_by(MarketDataOverride.price_date.desc(), MarketDataOverride.created_at.desc())
    )
    overrides = list(latest_override_result.scalars().all())
    if asset_identifiers:
        report_preparation_override_result = await db.execute(
            select(MarketDataOverride)
            .where(MarketDataOverride.user_id == user_id)
            .where(MarketDataOverride.asset_identifier.in_(asset_identifiers))
            .where(MarketDataOverride.source == PriceSource.MANUAL)
            .where(MarketDataOverride.price_date > as_of_date)
            .order_by(MarketDataOverride.price_date.desc(), MarketDataOverride.created_at.desc())
        )
        overrides.extend(report_preparation_override_result.scalars().all())
        overrides.sort(key=lambda override: override.price_date, reverse=True)
    latest_override = overrides[0] if overrides else None
    latest_override_by_asset: dict[str, MarketDataOverride] = {}
    for override in overrides:
        latest_override_by_asset.setdefault(override.asset_identifier, override)

    stock_prices: list[StockPrice] = []
    if asset_identifiers:
        stock_price_result = await db.execute(
            select(StockPrice)
            .where(StockPrice.symbol.in_(asset_identifiers))
            .where(StockPrice.price_date <= as_of_date)
            .order_by(StockPrice.price_date.desc(), StockPrice.created_at.desc(), StockPrice.source.asc())
        )
        stock_prices = list(stock_price_result.scalars().all())
    latest_stock_price_by_asset: dict[str, StockPrice] = {}
    for stock_price in stock_prices:
        latest_stock_price_by_asset.setdefault(stock_price.symbol, stock_price)

    price_dates: list[date] = []
    providers: set[str] = set()
    stale_holdings: list[str] = []
    for asset_identifier in asset_identifiers:
        override = latest_override_by_asset.get(asset_identifier)
        stock_price = latest_stock_price_by_asset.get(asset_identifier)
        atomic = latest_atomic_by_asset.get(asset_identifier)

        candidates: list[tuple[date, str, object, str | None]] = []
        if override is not None:
            candidates.append((override.price_date, "market_data_override", override.id, override.source.value))
        if stock_price is not None:
            candidates.append((stock_price.price_date, "stock_price", stock_price.id, stock_price.source))
        if atomic is not None:
            candidates.append((atomic.snapshot_date, "atomic_position", atomic.id, atomic.broker))

        if not candidates:
            stale_holdings.append(asset_identifier)
            continue

        evidence_date, source_kind, source_id, provider = max(candidates, key=lambda candidate: candidate[0])
        price_dates.append(evidence_date)
        source_links.add(_freshness_link(asset_identifier, source_kind, source_id, evidence_date))
        if provider:
            providers.add(provider)
        if evidence_date < as_of_date:
            stale_holdings.append(asset_identifier)

    latest_price_date = max(price_dates) if price_dates else None
    market_data_provider = ", ".join(sorted(providers)) if providers else None

    data_freshness = InvestmentPerformanceDataFreshness(
        latest_price_date=latest_price_date,
        market_data_provider=market_data_provider,
        stale=bool(stale_holdings),
        stale_holdings=sorted(stale_holdings),
        manual_override_basis=(
            f"{latest_override.asset_identifier}:{latest_override.price_date.isoformat()}"
            if latest_override is not None
            else None
        ),
    )
    if data_freshness.stale:
        notes.append("One or more market values use stale data relative to the requested as-of date.")

    return InvestmentPerformanceReportScheduleResponse(
        period_start=period_start,
        period_end=period_end,
        as_of_date=as_of_date,
        currency=currency,
        xirr=_percent(xirr),
        time_weighted_return=_percent(twr),
        money_weighted_return=_percent(mwr),
        realized_pnl=to_money(sum(realized_by_asset.values(), Decimal("0.00"))),
        unrealized_pnl=to_money(sum((row.unrealized_pnl for row in holding_rows), Decimal("0.00"))),
        dividend_income=to_money(sum(dividend_by_asset.values(), Decimal("0.00"))),
        dividend_yield=_percent(dividend_yield),
        holdings=holding_rows,
        allocation=allocation_rows,
        data_freshness=data_freshness,
        source_links=sorted(source_links),
        notes=notes,
    )
