"""``portfolio`` — the backend implementation of the ``portfolio`` package (#1422).

Investment position accounting: buy/sell/dividend transactions posted
through ``ledger.post_entry``, ``ManagedPosition``/``InvestmentLot``
bookkeeping, and the read-side holdings/P&L/allocation/performance queries.
See ``common/portfolio/contract.py`` for the full model and the positions-
only boundary (portfolio consumes prices/FX via ``pricing``'s published
surface, it never fetches or stores one — #1610).

The write-side accounting service (``InvestmentAccountingService``) landed
first (PR #1628); the read side followed in #1643 (holdings/P&L, allocation,
performance, and the report-schedule assembly moved from ``services/``),
plus the #1641 scope-discovery reads (``active_stock_symbols``/
``position_currencies``). The data-layer projections are still reserved
(declared in the contract's ``units`` with no module path).
"""

from __future__ import annotations

from src.portfolio.base import (
    AssetNotFoundError,
    InsufficientDataError,
    InvalidDateRangeError,
    InvestmentAccountingError,
    InvestmentAccountingValidationError,
    PerformanceError,
    PortfolioError,
    PortfolioNotFoundError,
    XIRRCalculationError,
)
from src.portfolio.extension import (
    InvestmentAccountingResult,
    InvestmentAccountingService,
    PortfolioService,
    active_stock_symbols,
    build_investment_performance_report_schedule,
    calculate_dividend_yield,
    calculate_money_weighted_return,
    calculate_time_weighted_return,
    calculate_xirr,
    get_asset_class_allocation,
    get_geography_allocation,
    get_sector_allocation,
    portfolio_service,
    position_currencies,
)
from src.portfolio.extension.api.assets import router as assets_router
from src.portfolio.extension.api.portfolio import router as portfolio_router
from src.portfolio.extension.positions import DepreciationResult, PositionService, PositionServiceError, ReconcileResult

# ORM models owned by this package (moved from src/models, #1675); imported
# eagerly so importing the package registers the mappers on Base.metadata.
# (MarketDataOverride/PriceSource moved to pricing — the observation store's
# domain owner — not here.)
from src.portfolio.orm.portfolio import (
    DividendIncome,
    DividendType,
    InvestmentLot,
    InvestmentTransaction,
    InvestmentTransactionType,
)

__all__ = [
    "AssetNotFoundError",
    "DepreciationResult",
    "DividendIncome",
    "DividendType",
    "InsufficientDataError",
    "InvalidDateRangeError",
    "InvestmentAccountingError",
    "InvestmentAccountingResult",
    "InvestmentAccountingService",
    "InvestmentAccountingValidationError",
    "InvestmentLot",
    "InvestmentTransaction",
    "InvestmentTransactionType",
    "PerformanceError",
    "PortfolioError",
    "PortfolioNotFoundError",
    "PortfolioService",
    "PositionService",
    "PositionServiceError",
    "ReconcileResult",
    "XIRRCalculationError",
    "active_stock_symbols",
    "build_investment_performance_report_schedule",
    "calculate_dividend_yield",
    "calculate_money_weighted_return",
    "calculate_time_weighted_return",
    "calculate_xirr",
    "get_asset_class_allocation",
    "get_geography_allocation",
    "get_sector_allocation",
    "portfolio_service",
    "position_currencies",
    "assets_router",
    "portfolio_router",
]
