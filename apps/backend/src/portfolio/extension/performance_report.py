"""Investment performance report-schedule assembly (EPIC-005)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import cast, overload
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import Currency, Money, to_money
from src.audit.ratio import Ratio
from src.extraction.orm.layer2 import AtomicPosition
from src.extraction.orm.layer3 import ManagedPosition, PositionStatus
from src.portfolio.base.errors import (
    AssetNotFoundError,
    InsufficientDataError,
    PerformanceError,
    PortfolioNotFoundError,
)
from src.portfolio.extension import allocation, performance
from src.portfolio.extension.holdings import portfolio_service
from src.pricing import MarketDataOverride, PriceSource, StockPrice, convert_money
from src.schemas.portfolio import (
    HoldingResponse,
    InvestmentPerformanceAllocationRow,
    InvestmentPerformanceDataFreshness,
    InvestmentPerformanceHoldingRow,
    InvestmentPerformanceMarketValuationSelection,
    InvestmentPerformanceReportScheduleResponse,
)


@overload
def _percent(value: Decimal) -> Decimal: ...


@overload
def _percent(value: None) -> None: ...


def _percent(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    ratio = Ratio.from_percent(value)
    return ratio.to_percent()


def _stock_symbol(asset_identifier: str) -> str:
    return asset_identifier.strip().upper()


def _market_valuation_selections(
    *,
    holdings: list[HoldingResponse],
    stock_prices_by_symbol: dict[str, StockPrice],
    as_of_date: date,
    used_report_preparation_evidence: bool,
) -> list[InvestmentPerformanceMarketValuationSelection]:
    """Publish only external prices that the point-in-time schedule actually rendered."""
    if used_report_preparation_evidence:
        return []

    selections: dict[tuple[str, UUID], InvestmentPerformanceMarketValuationSelection] = {}
    for holding in holdings:
        if holding.quantity == Decimal("0"):
            continue
        stock_price = stock_prices_by_symbol.get(_stock_symbol(holding.asset_identifier))
        if stock_price is None:
            continue
        observation_id = cast(UUID, stock_price.id)
        selections[(holding.asset_identifier, observation_id)] = InvestmentPerformanceMarketValuationSelection(
            asset_identifier=holding.asset_identifier,
            observation_id=observation_id,
            requested_as_of=as_of_date,
        )
    return [selections[key] for key in sorted(selections)]


def _source_document_links(source_documents: object) -> list[str]:
    if isinstance(source_documents, list):
        docs = source_documents
    elif isinstance(source_documents, dict):
        docs = source_documents.get("documents") or source_documents.get("source_documents") or [source_documents]
    else:
        docs = []

    return [
        f"{doc.get('doc_type') or doc.get('type') or 'source'}:{doc_id}"
        for doc in docs
        if isinstance(doc, dict) and (doc_id := doc.get("doc_id") or doc.get("id") or doc.get("source_id"))
    ]


def _freshness_link(asset_identifier: str, source_kind: str, source_id: object, evidence_date: date) -> str:
    return f"price_source:{source_kind}:{asset_identifier}:{source_id}:{evidence_date.isoformat()}"


async def _report_preparation_holdings(
    db: AsyncSession,
    user_id: UUID,
    as_of_date: date,
) -> list[HoldingResponse]:
    """Load current holdings only when post-period manual prices evidence report preparation."""
    override_rows = (
        await db.scalars(
            select(MarketDataOverride)
            .where(
                MarketDataOverride.user_id == user_id,
                MarketDataOverride.source == PriceSource.MANUAL,
                MarketDataOverride.price_date > as_of_date,
            )
            .order_by(MarketDataOverride.price_date.desc(), MarketDataOverride.created_at.desc())
        )
    ).all()
    override_assets = {override.asset_identifier for override in override_rows}
    if not override_assets:
        return []

    try:
        current_holdings = await portfolio_service.get_holdings(db=db, user_id=user_id, include_disposed=True)
    except (PortfolioNotFoundError, AssetNotFoundError):
        return []

    return [
        h for h in current_holdings if h.asset_identifier in override_assets and h.status == PositionStatus.ACTIVE
    ]


async def build_investment_performance_report_schedule(
    db: AsyncSession,
    user_id: UUID,
    *,
    period_start: date,
    period_end: date,
    as_of_date: date,
    currency: str,
) -> InvestmentPerformanceReportScheduleResponse:
    """Assemble the report-ready investment performance schedule."""
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
            await portfolio_service.get_holdings(db=db, user_id=user_id, as_of_date=as_of_date, include_disposed=True)
        )
    except (PortfolioNotFoundError, AssetNotFoundError):
        holdings = []

    if not holdings:
        holdings = await _report_preparation_holdings(db=db, user_id=user_id, as_of_date=as_of_date)
        used_report_preparation_evidence = bool(holdings)
        notes.append(
            "No holdings snapshot existed on or before the as-of date; the schedule used active holdings "
            "with post-period manual market-data overrides as report-preparation evidence."
            if used_report_preparation_evidence
            else "No portfolio holdings were available for the requested as-of date."
        )

    asset_identifiers = [holding.asset_identifier for holding in holdings]
    position_by_asset: dict[str, ManagedPosition] = (
        {
            p.asset_identifier: p
            for p in (
                await db.scalars(
                    select(ManagedPosition).where(
                        ManagedPosition.user_id == user_id,
                        ManagedPosition.asset_identifier.in_(asset_identifiers),
                    )
                )
            ).all()
        }
        if asset_identifiers
        else {}
    )

    async def _metric_or_note(metric_name: str, calculation):
        try:
            return await calculation()
        except (InsufficientDataError, PerformanceError) as exc:
            notes.append(f"{metric_name} unavailable: {exc}")
            return None

    xirr = await _metric_or_note(
        "XIRR", lambda: performance.calculate_xirr(db=db, user_id=user_id, as_of_date=as_of_date)
    )
    twr = await _metric_or_note(
        "TWR",
        lambda: performance.calculate_time_weighted_return(
            db=db, user_id=user_id, period_start=period_start, period_end=period_end
        ),
    )
    mwr = await _metric_or_note(
        "MWR", lambda: performance.calculate_money_weighted_return(db=db, user_id=user_id, as_of_date=as_of_date)
    )
    dividend_yield = await _metric_or_note(
        "Dividend yield", lambda: performance.calculate_dividend_yield(db=db, user_id=user_id, as_of_date=as_of_date)
    )

    realized_by_asset, realized_source_refs = await portfolio_service.get_realized_pnl_by_asset(
        db, user_id, start_date=period_start, end_date=period_end, target_currency=currency
    )
    source_links: set[str] = {"report_section:investment_performance", *realized_source_refs}
    dividend_by_asset = await portfolio_service.get_dividend_income_by_asset(
        db, user_id, start_date=period_start, end_date=period_end, target_currency=currency
    )

    holding_rows: list[InvestmentPerformanceHoldingRow] = []
    for holding in holdings:
        position = position_by_asset.get(holding.asset_identifier)
        base_money, acq_date = (
            (Money(holding.cost_basis, Currency.of(holding.currency)), holding.acquisition_date)
            if position is None
            else (position.cost_basis_money, position.acquisition_date)
        )
        cost_basis = (await convert_money(db, base_money, currency, acq_date, lazy_load=True)).quantize()
        market_value = to_money(holding.market_value)
        holding_rows.append(
            InvestmentPerformanceHoldingRow(
                asset_identifier=holding.asset_identifier,
                quantity=holding.quantity,
                cost_basis=cost_basis.amount,
                market_value=market_value,
                unrealized_pnl=to_money(market_value - cost_basis.amount),
                realized_pnl=to_money(realized_by_asset.get(holding.asset_identifier, Decimal("0.00"))),
                dividend_income=to_money(dividend_by_asset.get(holding.asset_identifier, Decimal("0.00"))),
                currency=holding.currency,
            )
        )

    allocation_rows: list[InvestmentPerformanceAllocationRow] = [
        InvestmentPerformanceAllocationRow(
            dimension=dimension,
            category=row.category,
            value=to_money(row.value),
            percentage=_percent(row.percentage),
            count=row.count,
        )
        for dimension, loader in (
            ("sector", allocation.get_sector_allocation),
            ("geography", allocation.get_geography_allocation),
            ("asset_class", allocation.get_asset_class_allocation),
        )
        for row in await loader(db=db, user_id=user_id, as_of_date=as_of_date)
    ]
    if used_report_preparation_evidence and not allocation_rows and holding_rows:
        total_market_value = sum((row.market_value for row in holding_rows), Decimal("0.00"))
        for dimension, attribute in (("sector", "sector"), ("geography", "geography"), ("asset_class", "asset_type")):
            grouped: dict[str, tuple[Decimal, int]] = {}
            for holding, holding_row in zip(holdings, holding_rows, strict=True):
                category = getattr(holding, attribute) or "Unclassified"
                cur_val, cur_cnt = grouped.get(category, (Decimal("0.00"), 0))
                grouped[category] = (cur_val + holding_row.market_value, cur_cnt + 1)
            for category, (value, count) in grouped.items():
                allocation_rows.append(
                    InvestmentPerformanceAllocationRow(
                        dimension=dimension,
                        category=category,
                        value=to_money(value),
                        percentage=Ratio.fraction_or_zero(value, total_market_value).to_percent(),
                        count=count,
                    )
                )
        notes.append("Allocation rows use report-preparation holdings when as-of allocation snapshots are unavailable.")

    latest_atomic_query = select(AtomicPosition).where(AtomicPosition.user_id == user_id)
    latest_atomic_query = (
        latest_atomic_query.where(AtomicPosition.asset_identifier.in_(asset_identifiers))
        if used_report_preparation_evidence and asset_identifiers
        else latest_atomic_query.where(AtomicPosition.snapshot_date <= as_of_date)
    )
    atomics = (
        await db.scalars(latest_atomic_query.order_by(AtomicPosition.snapshot_date.desc(), AtomicPosition.created_at.desc()))
    ).all()
    latest_atomic_by_asset: dict[str, AtomicPosition] = {}
    for atomic in atomics:
        latest_atomic_by_asset.setdefault(atomic.asset_identifier, atomic)
        source_links.update(_source_document_links(atomic.source_documents))

    overrides = list(
        (
            await db.scalars(
                select(MarketDataOverride)
                .where(MarketDataOverride.user_id == user_id, MarketDataOverride.price_date <= as_of_date)
                .order_by(MarketDataOverride.price_date.desc(), MarketDataOverride.created_at.desc())
            )
        ).all()
    )
    if asset_identifiers:
        prep_overrides = (
            await db.scalars(
                select(MarketDataOverride)
                .where(
                    MarketDataOverride.user_id == user_id,
                    MarketDataOverride.asset_identifier.in_(asset_identifiers),
                    MarketDataOverride.source == PriceSource.MANUAL,
                    MarketDataOverride.price_date > as_of_date,
                )
                .order_by(MarketDataOverride.price_date.desc(), MarketDataOverride.created_at.desc())
            )
        ).all()
        overrides.extend(prep_overrides)
        overrides.sort(key=lambda ov: ov.price_date, reverse=True)
    latest_override = overrides[0] if overrides else None
    latest_override_by_asset: dict[str, MarketDataOverride] = {}
    for ov in overrides:
        latest_override_by_asset.setdefault(ov.asset_identifier, ov)

    stock_symbols = {_stock_symbol(aid) for aid in asset_identifiers}
    latest_stock_price_by_symbol: dict[str, StockPrice] = {}
    if stock_symbols:
        for sp in (
            await db.scalars(
                select(StockPrice)
                .where(StockPrice.symbol.in_(stock_symbols), StockPrice.price_date <= as_of_date)
                .order_by(
                    StockPrice.price_date.desc(),
                    StockPrice.created_at.desc(),
                    StockPrice.source.asc(),
                    StockPrice.currency.asc(),
                    StockPrice.id.asc(),
                )
            )
        ).all():
            latest_stock_price_by_symbol.setdefault(sp.symbol, sp)

    price_dates: list[date] = []
    providers: set[str] = set()
    stale_holdings: list[str] = []
    for asset_identifier in asset_identifiers:
        candidates: list[tuple[date, str, object, str | None]] = []
        if (matched_ov := latest_override_by_asset.get(asset_identifier)) is not None:
            candidates.append((matched_ov.price_date, "market_data_override", matched_ov.id, matched_ov.source.value))
        if (matched_sp := latest_stock_price_by_symbol.get(_stock_symbol(asset_identifier))) is not None:
            candidates.append((matched_sp.price_date, "stock_price", matched_sp.id, matched_sp.source))
        if (matched_at := latest_atomic_by_asset.get(asset_identifier)) is not None:
            candidates.append((matched_at.snapshot_date, "atomic_position", matched_at.id, matched_at.broker))

        if not candidates:
            stale_holdings.append(asset_identifier)
            continue

        evidence_date, source_kind, source_id, provider = max(candidates, key=lambda c: c[0])
        price_dates.append(evidence_date)
        source_links.add(_freshness_link(asset_identifier, source_kind, source_id, evidence_date))
        if provider:
            providers.add(provider)
        if evidence_date < as_of_date:
            stale_holdings.append(asset_identifier)

    data_freshness = InvestmentPerformanceDataFreshness(
        latest_price_date=max(price_dates) if price_dates else None,
        market_data_provider=", ".join(sorted(providers)) if providers else None,
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
        market_valuation_selections=_market_valuation_selections(
            holdings=holdings,
            stock_prices_by_symbol=latest_stock_price_by_symbol,
            as_of_date=as_of_date,
            used_report_preparation_evidence=used_report_preparation_evidence,
        ),
        allocation=allocation_rows,
        data_freshness=data_freshness,
        source_links=sorted(source_links),
        notes=notes,
    )
