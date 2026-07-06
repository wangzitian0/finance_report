"""Typed error hierarchy for the portfolio package.

Moved verbatim from ``services/portfolio.py`` and ``services/
investment_accounting.py`` (standard-preserving move, Decision A — #1416):
same names, same messages, same hierarchy. The two families stay separate
(``PortfolioError`` for the read-side query service,
``InvestmentAccountingError`` for the write-side posting service) because
that's how the original code drew the line, and nothing here requires
unifying them.
"""

from __future__ import annotations


class PortfolioError(Exception):
    """Base exception for portfolio service errors."""


class PortfolioNotFoundError(PortfolioError):
    """Raised when portfolio positions are not found for a user."""


class InvalidDateRangeError(PortfolioError):
    """Raised when date range is invalid."""


class AssetNotFoundError(PortfolioError):
    """Raised when asset is not found."""


class InvestmentAccountingError(Exception):
    """Base exception for investment accounting errors."""


class InvestmentAccountingValidationError(InvestmentAccountingError):
    """Raised when an investment transaction cannot be posted."""
