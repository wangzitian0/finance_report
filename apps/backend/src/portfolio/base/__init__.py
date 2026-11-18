"""``portfolio.base`` — the pure, self-contained core.

Ships the error hierarchy (plain ``Exception`` subclasses, no ORM
references). The package's aggregate/entities and their enums are
taxonomy-only in the contract (no ``module=``): ``ManagedPosition``/
``InvestmentLot``/``InvestmentTransaction``/``DividendIncome`` live in this
package's own ``orm/portfolio.py`` (#3123), while ``AtomicPosition`` lives in
``extraction``'s ``orm/layer2.py`` (extraction owns parsed statement facts;
portfolio owns managed positions).
"""

from __future__ import annotations

from src.portfolio.base.errors import (
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
from src.portfolio.base.types import DividendEvent, TradeAccounts, TradeOrder

__all__ = [
    "AssetNotFoundError",
    "DividendEvent",
    "InsufficientDataError",
    "InvalidDateRangeError",
    "InvestmentAccountingError",
    "InvestmentAccountingValidationError",
    "PerformanceError",
    "PortfolioError",
    "PortfolioNotFoundError",
    "TradeAccounts",
    "TradeOrder",
    "XIRRCalculationError",
]
