"""``portfolio.extension`` — the domain services + impure edges.

Write side: ``InvestmentAccountingService`` (``post_buy``/``post_sell``/
``post_dividend``, moved from ``services/investment_accounting.py``) and
``PositionService`` (reconcile/depreciation).

Read side (#1643): the holdings/P&L query service (``holdings.py``, moved
from ``services/portfolio.py``), allocation breakdowns (``allocation.py``),
performance metrics (``performance.py``), and the investment performance
report-schedule assembly (``performance_report.py``). All FX conversion goes
through ``pricing``'s published surface — never ``services.fx``.

Scope discovery (#1641): ``discovery.py`` publishes ``active_stock_symbols``
and ``position_currencies`` — portfolio's answers to "what does this user
hold", composed by the delivery layer into the scopes passed to ``pricing``'s
crawl.
"""

from __future__ import annotations

from src.portfolio.extension.accounting import (
    InvestmentAccountingResult,
    InvestmentAccountingService,
)
from src.portfolio.extension.allocation import (
    get_asset_class_allocation,
    get_geography_allocation,
    get_sector_allocation,
)
from src.portfolio.extension.discovery import active_stock_symbols, position_currencies
from src.portfolio.extension.holdings import PortfolioService, portfolio_service
from src.portfolio.extension.performance import (
    calculate_dividend_yield,
    calculate_money_weighted_return,
    calculate_time_weighted_return,
    calculate_xirr,
)
from src.portfolio.extension.performance_report import (
    build_investment_performance_report_schedule,
)

__all__ = [
    "InvestmentAccountingResult",
    "InvestmentAccountingService",
    "PortfolioService",
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
