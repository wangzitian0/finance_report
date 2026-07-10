"""``portfolio`` — the backend implementation of the ``portfolio`` package (#1422).

Investment position accounting: buy/sell/dividend transactions posted
through ``ledger.post_entry``, ``ManagedPosition``/``InvestmentLot``
bookkeeping, and the read-side holdings/P&L/allocation/performance queries.
See ``common/portfolio/contract.py`` for the full model and the positions-
only boundary (portfolio consumes prices via ``pricing.resolve()``, it never
fetches or stores one — #1610).

This commit ships the ``base/`` error hierarchy and ``InvestmentAccountingService``
(the write-side accounting service). The read-side holdings/P&L queries,
allocation/performance, and the data-layer projections are reserved
(declared in the contract's ``units`` with no module path) for later
commits — same incremental pattern the pricing cutover (#1610, PR #1617)
used.
"""

from __future__ import annotations

from src.portfolio.base import (
    AssetNotFoundError,
    InvalidDateRangeError,
    InvestmentAccountingError,
    InvestmentAccountingValidationError,
    PortfolioError,
    PortfolioNotFoundError,
)
from src.portfolio.extension import (
    InvestmentAccountingResult,
    InvestmentAccountingService,
)
from src.portfolio.extension.positions import DepreciationResult, PositionService, PositionServiceError, ReconcileResult

__all__ = [
    "AssetNotFoundError",
    "DepreciationResult",
    "InvalidDateRangeError",
    "InvestmentAccountingError",
    "InvestmentAccountingResult",
    "InvestmentAccountingService",
    "InvestmentAccountingValidationError",
    "PortfolioError",
    "PortfolioNotFoundError",
    "PositionService",
    "PositionServiceError",
    "ReconcileResult",
]
