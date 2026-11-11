"""``reporting`` — calculation-over-ledger domain package."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

_MODULES: dict[str, tuple[str, ...]] = {
    "src.reporting.base.cash_flow_types": (
        "CashFlowItem",
        "CashFlowLineEventsPage",
        "CashFlowPreview",
        "CashFlowResponse",
        "CashFlowSummary",
    ),
    "src.reporting.base.data_quality_types": (
        "InvariantStatus",
        "MonthContinuityBucket",
        "PersonalDataQualityHealthResponse",
        "QualityActionItem",
        "QualityGrade",
    ),
    "src.reporting.base.diagnostics": ("EquationDiagnosticCategory", "EquationDiagnosticResult"),
    "src.reporting.base.l1_registry": ("is_valid_line_for_framework",),
    "src.reporting.base.package_contribution": ("PackageSectionContribution",),
    "src.reporting.base.package_decision": ("personal_report_package_target",),
    "src.reporting.base.report_package_contract": (
        "PERSONAL_REPORT_PACKAGE_CONTRACT",
        "PERSONAL_REPORT_PACKAGE_NOTES",
    ),
    "src.reporting.base.types": (
        "DEFAULT_INCLUDE_RESTRICTED",
        "PACKAGE_INCLUDE_RESTRICTED",
        "PersonalReportingFrameworkId",
        "PolicyDimension",
        "ReportLineId",
    ),
    "src.reporting.extension._core": ("_aggregate_balances_sql", "_aggregate_net_income_sql"),
    "src.reporting.extension.annualized_income": ("generate_annualized_income_schedule",),
    "src.reporting.extension.balance_sheet": ("generate_balance_sheet", "register_manual_valuation_lines_provider"),
    "src.reporting.extension.cash_flow": (
        "cash_flow_line_events",
        "cash_flow_period",
        "cash_flow_preview",
    ),
    "src.reporting.extension.data_quality_service": ("compute_personal_data_quality",),
    "src.reporting.extension.diagnostics": ("diagnose_equation_imbalance", "run_balance_sheet_diagnostics"),
    "src.reporting.extension.framework_policy": ("derive_user_framework_policy_result",),
    "src.reporting.extension.framework_report": (
        "assemble_framework_balance_sheet",
        "assemble_framework_income_statement",
    ),
    "src.reporting.extension.income_statement": ("generate_income_statement",),
    "src.reporting.extension.lineage": ("get_account_lineage",),
    "src.reporting.extension.net_worth": (
        "get_account_trend",
        "get_category_breakdown",
        "get_net_worth_allocation_schedule",
        "get_net_worth_timeseries",
    ),
    "src.reporting.extension.package_document": (
        "PackageAssembler",
        "current_package_readiness",
        "package_preview",
        "personal_report_package_decision_ref",
        "report_coverage",
    ),
    "src.reporting.extension.report_csv": (
        "render_balance_sheet_csv",
        "render_cash_flow_csv",
        "render_income_statement_csv",
    ),
    "src.reporting.extension.report_package": (
        "PackageDocumentVersionError",
        "jsonable",
        "package_currency",
        "package_dates",
        "package_snapshot_csv",
        "package_snapshot_document",
        "package_snapshot_response",
        "package_snapshot_summary",
    ),
    "src.reporting.extension.report_traceability": ("build_personal_report_package_traceability_payload",),
    "src.reporting.extension.reporting_calc": (
        "MAX_NET_WORTH_DAILY_POINTS",
        "AnnualizedIncomeTotals",
        "ReportError",
        "_add_months",
        "_combine_provenance",
        "_iter_periods",
        "_month_end",
        "_month_start",
        "_normalize_currency",
        "_provenance_from_source_type",
        "_quantize_money",
        "_quarter_start",
        "_signed_amount",
        "income_bucket",
        "resolve_line_currency",
    ),
    "src.reporting.extension.reporting_snapshot": ("ReportingSnapshotService",),
    "src.reporting.orm": ("ReportSnapshot", "ReportType"),
}
_EXPORTS = {
    "generate_cash_flow": "src.reporting.extension.cash_flow",
    **{name: mod for mod, names in _MODULES.items() for name in names},
}

__all__ = [
    "MAX_NET_WORTH_DAILY_POINTS",
    "PERSONAL_REPORT_PACKAGE_CONTRACT",
    "PERSONAL_REPORT_PACKAGE_NOTES",
    "PackageAssembler",
    "PackageSectionContribution",
    "personal_report_package_target",
    "personal_report_package_decision_ref",
    "current_package_readiness",
    "report_coverage",
    "package_preview",
    "PackageDocumentVersionError",
    "EquationDiagnosticCategory",
    "EquationDiagnosticResult",
    "diagnose_equation_imbalance",
    "run_balance_sheet_diagnostics",
    "AnnualizedIncomeTotals",
    "CashFlowItem",
    "CashFlowLineEventsPage",
    "CashFlowPreview",
    "CashFlowResponse",
    "CashFlowSummary",
    "PersonalDataQualityHealthResponse",
    "QualityGrade",
    "InvariantStatus",
    "MonthContinuityBucket",
    "QualityActionItem",
    "compute_personal_data_quality",
    "DEFAULT_INCLUDE_RESTRICTED",
    "PACKAGE_INCLUDE_RESTRICTED",
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
    "derive_user_framework_policy_result",
    "generate_balance_sheet",
    "generate_annualized_income_schedule",
    "cash_flow_line_events",
    "cash_flow_period",
    "cash_flow_preview",
    "generate_cash_flow",
    "generate_income_statement",
    "get_account_lineage",
    "get_account_trend",
    "get_category_breakdown",
    "get_net_worth_allocation_schedule",
    "get_net_worth_timeseries",
    "income_bucket",
    "is_valid_line_for_framework",
    "jsonable",
    "package_currency",
    "package_dates",
    "package_snapshot_csv",
    "package_snapshot_document",
    "package_snapshot_response",
    "package_snapshot_summary",
    "register_manual_valuation_lines_provider",
    "render_balance_sheet_csv",
    "render_cash_flow_csv",
    "render_income_statement_csv",
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
    from src.reporting.base.cash_flow_types import (
        CashFlowItem,
        CashFlowLineEventsPage,
        CashFlowPreview,
        CashFlowResponse,
        CashFlowSummary,
    )
    from src.reporting.base.data_quality_types import (
        InvariantStatus,
        MonthContinuityBucket,
        PersonalDataQualityHealthResponse,
        QualityActionItem,
        QualityGrade,
    )
    from src.reporting.base.diagnostics import (
        EquationDiagnosticCategory,
        EquationDiagnosticResult,
    )
    from src.reporting.base.l1_registry import is_valid_line_for_framework
    from src.reporting.base.package_contribution import PackageSectionContribution
    from src.reporting.base.package_decision import personal_report_package_target
    from src.reporting.base.report_package_contract import (
        PERSONAL_REPORT_PACKAGE_CONTRACT,
        PERSONAL_REPORT_PACKAGE_NOTES,
    )
    from src.reporting.base.types import (
        DEFAULT_INCLUDE_RESTRICTED,
        PACKAGE_INCLUDE_RESTRICTED,
        PersonalReportingFrameworkId,
        PolicyDimension,
        ReportLineId,
    )
    from src.reporting.extension._core import _aggregate_balances_sql, _aggregate_net_income_sql
    from src.reporting.extension.annualized_income import generate_annualized_income_schedule
    from src.reporting.extension.balance_sheet import (
        generate_balance_sheet,
        register_manual_valuation_lines_provider,
    )
    from src.reporting.extension.cash_flow import (
        cash_flow_line_events,
        cash_flow_period,
        cash_flow_preview,
        generate_cash_flow,
    )
    from src.reporting.extension.data_quality_service import compute_personal_data_quality
    from src.reporting.extension.diagnostics import (
        diagnose_equation_imbalance,
        run_balance_sheet_diagnostics,
    )
    from src.reporting.extension.framework_policy import derive_user_framework_policy_result
    from src.reporting.extension.framework_report import (
        assemble_framework_balance_sheet,
        assemble_framework_income_statement,
    )
    from src.reporting.extension.income_statement import generate_income_statement
    from src.reporting.extension.lineage import get_account_lineage
    from src.reporting.extension.net_worth import (
        get_account_trend,
        get_category_breakdown,
        get_net_worth_allocation_schedule,
        get_net_worth_timeseries,
    )
    from src.reporting.extension.package_document import (
        PackageAssembler,
        current_package_readiness,
        package_preview,
        personal_report_package_decision_ref,
        report_coverage,
    )
    from src.reporting.extension.report_csv import (
        render_balance_sheet_csv,
        render_cash_flow_csv,
        render_income_statement_csv,
    )
    from src.reporting.extension.report_package import (
        PackageDocumentVersionError,
        jsonable,
        package_currency,
        package_dates,
        package_snapshot_csv,
        package_snapshot_document,
        package_snapshot_response,
        package_snapshot_summary,
    )
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
