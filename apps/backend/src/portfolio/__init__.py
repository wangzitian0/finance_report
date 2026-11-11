"""``portfolio`` — investment position accounting, holdings, allocation, and performance."""

from __future__ import annotations

from src.portfolio.base import (
    AssetNotFoundError,
    DividendEvent,
    InsufficientDataError,
    InvalidDateRangeError,
    InvestmentAccountingError,
    InvestmentAccountingValidationError,
    PerformanceError,
    PortfolioError,
    PortfolioNotFoundError,
    TradeAccounts,
    TradeOrder,
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
    "DividendEvent",
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
    "TradeAccounts",
    "TradeOrder",
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
]
