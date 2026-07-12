"""``portfolio.base`` — the pure, self-contained core.

Ships the error hierarchy (plain ``Exception`` subclasses, no ORM
references). The package's aggregate/entities (``ManagedPosition``,
``InvestmentLot``, ``InvestmentTransaction``, ``DividendIncome``,
``AtomicPosition``) and their enums stay in the unregistered ``src/models/``
(taxonomy-only in the contract, no ``module=`` — same deferral extraction
and ledger already made) until Stage-4 cross-domain FK surgery.
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
