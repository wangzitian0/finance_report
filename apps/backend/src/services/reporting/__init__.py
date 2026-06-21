"""Reporting service for financial statements and analytics (package).

Split from a single 2143-line module into per-statement submodules; the public
import surface (and the re-export of ``reporting_calc`` primitives, AC25.1.1) is
preserved via these re-exports.
"""

from src.services.reporting._core import (
    _aggregate_balances_sql,
    _aggregate_net_income_sql,
)
from src.services.reporting.balance_sheet import generate_balance_sheet
from src.services.reporting.cash_flow import generate_cash_flow
from src.services.reporting.income_statement import generate_income_statement
from src.services.reporting.lineage import get_account_lineage
from src.services.reporting.net_worth import (
    get_account_trend,
    get_category_breakdown,
    get_net_worth_allocation_schedule,
    get_net_worth_timeseries,
)
from src.services.reporting_calc import (
    MAX_NET_WORTH_DAILY_POINTS,
    ReportError,
    _add_months,
    _combine_provenance,
    _iter_periods,
    _month_end,
    _month_start,
    _normalize_currency,
    _provenance_from_source_type,
    _quantize_money,
    _quarter_start,
    _signed_amount,
    _worst_confidence_tier,
)

__all__ = [
    "MAX_NET_WORTH_DAILY_POINTS",
    "ReportError",
    "_add_months",
    "_aggregate_balances_sql",
    "_aggregate_net_income_sql",
    "_combine_provenance",
    "_iter_periods",
    "_month_end",
    "_month_start",
    "_normalize_currency",
    "_provenance_from_source_type",
    "_quantize_money",
    "_quarter_start",
    "_signed_amount",
    "_worst_confidence_tier",
    "generate_balance_sheet",
    "generate_cash_flow",
    "generate_income_statement",
    "get_account_lineage",
    "get_account_trend",
    "get_category_breakdown",
    "get_net_worth_allocation_schedule",
    "get_net_worth_timeseries",
]
