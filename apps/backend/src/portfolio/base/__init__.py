"""``portfolio.base`` — the pure, self-contained core.

This commit ships only the error hierarchy (plain ``Exception`` subclasses,
no ORM references). The package's aggregate/entities (``ManagedPosition``,
``InvestmentLot``, ``InvestmentTransaction``, ``DividendIncome``,
``AtomicPosition``) and their enums stay in the unregistered ``src/models/``
(taxonomy-only in the contract, no ``module=`` — same deferral extraction
and ledger already made) until Stage-4 cross-domain FK surgery.
"""

from __future__ import annotations

from src.portfolio.base.errors import (
    AssetNotFoundError,
    InvalidDateRangeError,
    InvestmentAccountingError,
    InvestmentAccountingValidationError,
    PortfolioError,
    PortfolioNotFoundError,
)

__all__ = [
    "AssetNotFoundError",
    "InvalidDateRangeError",
    "InvestmentAccountingError",
    "InvestmentAccountingValidationError",
    "PortfolioError",
    "PortfolioNotFoundError",
]
