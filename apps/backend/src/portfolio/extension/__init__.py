"""``portfolio.extension`` — the domain services + impure edges.

Reserved for later commits (issue #1422 P2-P4): the write-side accounting
service (``post_buy``/``post_sell``/``post_dividend``, moved from
``services/investment_accounting.py``), the read-side holdings/P&L queries
+ repository port/adapter (moved from ``services/portfolio.py``), and
allocation/performance/report assembly (moved from ``services/
allocation.py``/``performance.py``/``performance_report.py``). See
``common/portfolio/contract.py`` — these are declared as taxonomy-only
reserved units until then.
"""

from __future__ import annotations

__all__: list[str] = []
