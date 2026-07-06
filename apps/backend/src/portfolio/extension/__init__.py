"""``portfolio.extension`` — the domain services + impure edges.

Real this commit: ``InvestmentAccountingService`` (the write-side accounting
service — ``post_buy``/``post_sell``/``post_dividend``, moved from
``services/investment_accounting.py``).

Reserved for later commits (issue #1422 P3-P4): the read-side holdings/P&L
queries + repository port/adapter (moved from ``services/portfolio.py``),
and allocation/performance/report assembly (moved from ``services/
allocation.py``/``performance.py``/``performance_report.py``). See
``common/portfolio/contract.py`` — these are declared as taxonomy-only
reserved units until then.
"""

from __future__ import annotations

from src.portfolio.extension.accounting import (
    InvestmentAccountingResult,
    InvestmentAccountingService,
)

__all__ = [
    "InvestmentAccountingResult",
    "InvestmentAccountingService",
]
