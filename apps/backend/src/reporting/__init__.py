"""``reporting`` — the backend implementation of the ``reporting`` package.

The calculation-over-ledger domain (see ``common/reporting/contract.py`` and
``common/reporting/readme.md``): statement generation (balance sheet / income
statement / cash flow / net worth / lineage), framework-aware report assembly,
the personal report package (readiness, traceability, notes, snapshot export),
the confidence metric, and the pure calculation primitives
(``extension/reporting_calc.py``, AC-reporting.dry-ssot.1).

Physically folded out of ``apps/backend/src/services/`` by #1666 (umbrella
#1416). The published language below is the package's entire external surface
— consumers (routers, the app composition root, the advisor service) import
from this root only. FX conversion and the manual-valuation lines builder are
*injected* at the composition root (``register_fx_gateway`` /
``register_manual_valuation_lines_provider``) so reporting never imports
``pricing``'s implementation directly, even though pricing owns both
(the FX lookup surface and manual valuation observations/staleness, #1610).

Manual valuation is deliberately NOT part of this package's own code —
``pricing/extension/valuation.py`` owns it (#1610 re-homed it from the
``services/reporting/manual_valuation.py`` survivor of the #1666 fold).
"""

from src.reporting.base.l1_registry import is_valid_line_for_framework
from src.reporting.base.report_package_contract import (
    PERSONAL_REPORT_PACKAGE_CONTRACT,
    PERSONAL_REPORT_PACKAGE_NOTES,
)
from src.reporting.extension._core import (
    _aggregate_balances_sql,
    _aggregate_net_income_sql,
)
from src.reporting.extension.balance_sheet import (
    generate_balance_sheet,
    register_manual_valuation_lines_provider,
)
from src.reporting.extension.cash_flow import generate_cash_flow
from src.reporting.extension.confidence_metric import ConfidenceMetricService
from src.reporting.extension.confidence_tier import derive_reconciliation_score_tier
from src.reporting.extension.framework_policy import derive_user_framework_policy_result
from src.reporting.extension.framework_report import (
    assemble_framework_balance_sheet,
    assemble_framework_income_statement,
)
from src.reporting.extension.fx_gateway import register_fx_gateway
from src.reporting.extension.income_statement import generate_income_statement
from src.reporting.extension.lineage import get_account_lineage
from src.reporting.extension.net_worth import (
    get_account_trend,
    get_category_breakdown,
    get_net_worth_allocation_schedule,
    get_net_worth_timeseries,
)
from src.reporting.extension.report_package import (
    jsonable,
    package_currency,
    package_dates,
    package_snapshot_csv,
    package_snapshot_response,
    package_snapshot_status,
    package_snapshot_summary,
)
from src.reporting.extension.report_readiness import get_personal_report_package_readiness
from src.reporting.extension.report_traceability import (
    build_personal_report_package_traceability_payload,
)
from src.reporting.extension.reporting_calc import (
    MAX_NET_WORTH_DAILY_POINTS,
    AnnualizedIncomeTotals,
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
    income_bucket,
    resolve_line_currency,
)
from src.reporting.extension.reporting_snapshot import ReportingSnapshotService

__all__ = [
    "MAX_NET_WORTH_DAILY_POINTS",
    "PERSONAL_REPORT_PACKAGE_CONTRACT",
    "PERSONAL_REPORT_PACKAGE_NOTES",
    "AnnualizedIncomeTotals",
    "ConfidenceMetricService",
    "ReportError",
    "ReportingSnapshotService",
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
    "assemble_framework_balance_sheet",
    "assemble_framework_income_statement",
    "build_personal_report_package_traceability_payload",
    "derive_reconciliation_score_tier",
    "derive_user_framework_policy_result",
    "generate_balance_sheet",
    "generate_cash_flow",
    "generate_income_statement",
    "get_account_lineage",
    "get_account_trend",
    "get_category_breakdown",
    "get_net_worth_allocation_schedule",
    "get_net_worth_timeseries",
    "get_personal_report_package_readiness",
    "income_bucket",
    "is_valid_line_for_framework",
    "jsonable",
    "package_currency",
    "package_dates",
    "package_snapshot_csv",
    "package_snapshot_response",
    "package_snapshot_status",
    "package_snapshot_summary",
    "register_fx_gateway",
    "register_manual_valuation_lines_provider",
    "resolve_line_currency",
]
