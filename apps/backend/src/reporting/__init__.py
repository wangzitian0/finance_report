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

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

_EXPORTS = {
    "MAX_NET_WORTH_DAILY_POINTS": "src.reporting.extension.reporting_calc",
    "PERSONAL_REPORT_PACKAGE_CONTRACT": "src.reporting.base.report_package_contract",
    "PERSONAL_REPORT_PACKAGE_NOTES": "src.reporting.base.report_package_contract",
    "AnnualizedIncomeTotals": "src.reporting.extension.reporting_calc",
    "ConfidenceMetricService": "src.reporting.extension.confidence_metric",
    "PersonalReportingFrameworkId": "src.reporting.base.types",
    "PolicyDimension": "src.reporting.base.types",
    "ReportError": "src.reporting.extension.reporting_calc",
    "ReportLineId": "src.reporting.base.types",
    "ReportSnapshot": "src.reporting.orm",
    "ReportType": "src.reporting.orm",
    "ReportingSnapshotService": "src.reporting.extension.reporting_snapshot",
    "_add_months": "src.reporting.extension.reporting_calc",
    "_aggregate_balances_sql": "src.reporting.extension._core",
    "_aggregate_net_income_sql": "src.reporting.extension._core",
    "_combine_provenance": "src.reporting.extension.reporting_calc",
    "_iter_periods": "src.reporting.extension.reporting_calc",
    "_month_end": "src.reporting.extension.reporting_calc",
    "_month_start": "src.reporting.extension.reporting_calc",
    "_normalize_currency": "src.reporting.extension.reporting_calc",
    "_provenance_from_source_type": "src.reporting.extension.reporting_calc",
    "_quantize_money": "src.reporting.extension.reporting_calc",
    "_quarter_start": "src.reporting.extension.reporting_calc",
    "_signed_amount": "src.reporting.extension.reporting_calc",
    "assemble_framework_balance_sheet": "src.reporting.extension.framework_report",
    "assemble_framework_income_statement": "src.reporting.extension.framework_report",
    "build_personal_report_package_traceability_payload": "src.reporting.extension.report_traceability",
    "derive_reconciliation_score_tier": "src.reporting.extension.confidence_tier",
    "derive_user_framework_policy_result": "src.reporting.extension.framework_policy",
    "generate_balance_sheet": "src.reporting.extension.balance_sheet",
    "generate_cash_flow": "src.reporting.extension.cash_flow",
    "generate_income_statement": "src.reporting.extension.income_statement",
    "get_account_lineage": "src.reporting.extension.lineage",
    "get_account_trend": "src.reporting.extension.net_worth",
    "get_category_breakdown": "src.reporting.extension.net_worth",
    "get_net_worth_allocation_schedule": "src.reporting.extension.net_worth",
    "get_net_worth_timeseries": "src.reporting.extension.net_worth",
    "get_personal_report_package_readiness": "src.reporting.extension.report_readiness",
    "income_bucket": "src.reporting.extension.reporting_calc",
    "is_valid_line_for_framework": "src.reporting.base.l1_registry",
    "jsonable": "src.reporting.extension.report_package",
    "package_currency": "src.reporting.extension.report_package",
    "package_dates": "src.reporting.extension.report_package",
    "package_snapshot_csv": "src.reporting.extension.report_package",
    "package_snapshot_response": "src.reporting.extension.report_package",
    "package_snapshot_status": "src.reporting.extension.report_package",
    "package_snapshot_summary": "src.reporting.extension.report_package",
    "register_fx_gateway": "src.reporting.extension.fx_gateway",
    "register_manual_valuation_lines_provider": "src.reporting.extension.balance_sheet",
    "resolve_line_currency": "src.reporting.extension.reporting_calc",
}

__all__ = [
    "MAX_NET_WORTH_DAILY_POINTS",
    "PERSONAL_REPORT_PACKAGE_CONTRACT",
    "PERSONAL_REPORT_PACKAGE_NOTES",
    "AnnualizedIncomeTotals",
    "ConfidenceMetricService",
    "PersonalReportingFrameworkId",
    "PolicyDimension",
    "ReportError",
    "ReportLineId",
    "ReportSnapshot",
    "ReportType",
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


def __getattr__(name: str) -> object:
    """Resolve published names lazily so delivery schemas can import base types."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module), name)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from src.reporting.base.l1_registry import is_valid_line_for_framework
    from src.reporting.base.report_package_contract import (
        PERSONAL_REPORT_PACKAGE_CONTRACT,
        PERSONAL_REPORT_PACKAGE_NOTES,
    )
    from src.reporting.base.types import PersonalReportingFrameworkId, PolicyDimension, ReportLineId
    from src.reporting.extension._core import _aggregate_balances_sql, _aggregate_net_income_sql
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
    from src.reporting.extension.report_traceability import build_personal_report_package_traceability_payload
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
        income_bucket,
        resolve_line_currency,
    )
    from src.reporting.extension.reporting_snapshot import ReportingSnapshotService
    from src.reporting.orm import ReportSnapshot, ReportType
