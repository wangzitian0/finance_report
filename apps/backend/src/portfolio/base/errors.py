"""Typed error hierarchy for the portfolio package.

Moved verbatim from ``services/portfolio.py``, ``services/performance.py``,
and ``services/investment_accounting.py`` (standard-preserving move,
Decision A — #1416): same names, same messages, same hierarchy. The three
families stay separate (``PortfolioError`` for the read-side query service,
``PerformanceError`` for the return/yield metric calculations,
``InvestmentAccountingError`` for the write-side posting service) because
that's how the original code drew the line, and nothing here requires
unifying them.
"""

from __future__ import annotations

from src.platform.base.errors import DomainError, PreconditionFailedError, ResourceNotFoundError


class PortfolioError(DomainError):
    """Base exception for portfolio service errors."""


class PortfolioNotFoundError(ResourceNotFoundError, PortfolioError):
    """Raised when portfolio positions are not found for a user."""


class AssetNotFoundError(ResourceNotFoundError, PortfolioError):
    """Raised when asset is not found."""


class PerformanceError(DomainError):
    """Base exception for performance calculation errors."""


class InsufficientDataError(PerformanceError):
    """Raised when insufficient data for performance calculation."""


class XIRRCalculationError(PerformanceError):
    """Raised when XIRR calculation fails to converge."""


class InvestmentAccountingError(DomainError):
    """Base exception for investment accounting errors."""


class InvestmentAccountingValidationError(PreconditionFailedError, InvestmentAccountingError):
    """Raised when an investment transaction cannot be posted."""
