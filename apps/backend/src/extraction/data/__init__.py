"""``extraction.data`` — projection sinks.

Per the data-sink rule nothing in ``base/`` or ``extension/`` may import this
layer.
"""

from __future__ import annotations

from src.extraction.data.account_coverage import (
    DEFAULT_STALE_AFTER_DAYS,
    StatementCoverageRow,
    get_account_statement_coverage,
)

__all__ = [
    "DEFAULT_STALE_AFTER_DAYS",
    "StatementCoverageRow",
    "get_account_statement_coverage",
]
