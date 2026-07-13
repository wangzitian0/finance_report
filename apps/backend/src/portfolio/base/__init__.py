"""``portfolio.base`` — the pure, self-contained core.

Ships the error hierarchy (plain ``Exception`` subclasses, no ORM
references). The package's aggregate/entities and their enums are
taxonomy-only in the contract (no ``module=``): ``InvestmentLot``/
``InvestmentTransaction``/``DividendIncome`` live in this package's own
``orm/portfolio.py`` (#1675 D5), while ``ManagedPosition``/``AtomicPosition``
live in ``extraction``'s ``orm/layer3.py`` (#1675 D4+D5c — extraction owns
the fact family's ORM; portfolio imports the published entities).
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

__all__ = [
    "AssetNotFoundError",
    "InsufficientDataError",
    "InvalidDateRangeError",
    "InvestmentAccountingError",
    "InvestmentAccountingValidationError",
    "PerformanceError",
    "PortfolioError",
    "PortfolioNotFoundError",
    "XIRRCalculationError",
]
