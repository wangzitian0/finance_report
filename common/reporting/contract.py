"""The ``reporting`` package's machine-checkable :class:`PackageContract`.

This contract records the reporting-domain cutover boundary for Stage 4 of the
package migration umbrella (#1416, issue #1424): reporting remains the
calculation-over-ledger package and now declares its building blocks with
``units=[Unit(kind=...)]``.

Scope correction (2026-07-06): ``manual_valuation.py`` belongs to the pricing
cutover (#1610). Reporting keeps confidence-tier mapping and report assembly;
pricing owns valuation-observation staleness facts.
"""

from __future__ import annotations

from common.meta.package_contract import Invariant, Kind, PackageContract, Unit

CONTRACT = PackageContract(
    name="reporting",
    status="draft",
    tier=None,
    depends_on=[
        "audit",
        "ledger",
        "portfolio",
        "pricing",
        "extraction",
        "platform",
        "observability",
        "config",
    ],
    roles=["base", "extension", "data"],
    units=[
        # ── base (taxonomy-only while services/ fold is still in progress) ──
        Unit(name="ReportLine", kind=Kind.VALUE_OBJECT),
        Unit(name="BalanceSheetResponse", kind=Kind.VALUE_OBJECT),
        Unit(name="IncomeStatementResponse", kind=Kind.VALUE_OBJECT),
        Unit(name="CashFlowResponse", kind=Kind.VALUE_OBJECT),
        Unit(name="FrameworkPolicyDecision", kind=Kind.VALUE_OBJECT),
        Unit(name="FrameworkPolicyGap", kind=Kind.VALUE_OBJECT),
        Unit(name="FrameworkPolicyMatrix", kind=Kind.VALUE_OBJECT),
        Unit(name="PeriodSpan", kind=Kind.VALUE_OBJECT),
        Unit(name="AnnualizedIncomeTotals", kind=Kind.VALUE_OBJECT),
        Unit(name="NetWorthTimeSeriesPoint", kind=Kind.VALUE_OBJECT),
        Unit(name="AccountLineageLine", kind=Kind.VALUE_OBJECT),
        Unit(name="ReportSnapshot", kind=Kind.AGGREGATE_ROOT),
        # ── extension (report generation + lanes) ──
        Unit(
            name="generate_balance_sheet",
            kind=Kind.DOMAIN_SERVICE,
            module="balance_sheet.py",
        ),
        Unit(
            name="generate_income_statement",
            kind=Kind.DOMAIN_SERVICE,
            module="income_statement.py",
        ),
        Unit(
            name="generate_cash_flow",
            kind=Kind.DOMAIN_SERVICE,
            module="cash_flow.py",
        ),
        Unit(
            name="_aggregate_balances_sql",
            kind=Kind.DOMAIN_SERVICE,
            module="_core.py",
        ),
        Unit(
            name="_aggregate_net_income_sql",
            kind=Kind.DOMAIN_SERVICE,
            module="_core.py",
        ),
        Unit(
            name="get_net_worth_timeseries",
            kind=Kind.DOMAIN_SERVICE,
            module="net_worth.py",
        ),
        Unit(
            name="get_net_worth_allocation_schedule",
            kind=Kind.DOMAIN_SERVICE,
            module="net_worth.py",
        ),
        Unit(name="get_category_breakdown", kind=Kind.DOMAIN_SERVICE, module="net_worth.py"),
        Unit(name="get_account_trend", kind=Kind.DOMAIN_SERVICE, module="net_worth.py"),
        Unit(name="get_account_lineage", kind=Kind.DOMAIN_SERVICE, module="lineage.py"),
        Unit(
            name="ReportingReadRepository",
            kind=Kind.REPOSITORY,
        ),
        # ── data (projection / sink declarations) ──
        Unit(name="ReportSnapshotProjection", kind=Kind.PROJECTION),
        Unit(name="ReportReadinessProjection", kind=Kind.PROJECTION),
        Unit(name="ReportTraceabilityProjection", kind=Kind.PROJECTION),
        Unit(name="AccountLineageTreeProjection", kind=Kind.PROJECTION),
        Unit(name="ConfidenceTierAggregationProjection", kind=Kind.PROJECTION),
        Unit(name="FrameworkPolicyDecisionProjection", kind=Kind.PROJECTION),
    ],
    implementations={"be": "apps/backend/src/services/reporting", "fe": None},
    interface=[
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
    ],
    events=[],
    invariants=[
        Invariant(
            id="interface-equals-published-language",
            statement=(
                "The published language (contract.interface) equals __init__.__all__."
            ),
            test=(
                "tests/tooling/test_reporting_package.py"
                "::test_AC_reporting_1_1_only_all_is_the_published_language"
            ),
        ),
        Invariant(
            id="reporting-cutover-inventory-declared",
            statement=(
                "Reporting statement generators/core lanes are declared in units and mapped to the current implementation inventory."
            ),
            test=(
                "tests/tooling/test_reporting_package.py"
                "::test_AC_reporting_1_2_cutover_inventory_is_declared"
            ),
        ),
        Invariant(
            id="manual-valuation-excluded-from-reporting-language",
            statement=(
                "manual_valuation stays out of reporting's published language; pricing owns valuation observations/staleness."
            ),
            test=(
                "tests/tooling/test_reporting_package.py"
                "::test_AC_reporting_1_3_manual_valuation_is_not_published_reporting_surface"
            ),
        ),
        Invariant(
            id="passes-own-governance-gate",
            statement="check_package_contract validates reporting with no violations.",
            test=(
                "tests/tooling/test_reporting_package.py"
                "::test_AC_reporting_1_4_package_contract_gate_passes"
            ),
        ),
    ],
    # The reporting AC transfer from EPIC-owned rows to package roadmap ACs lands
    # in a follow-up commit once the full services/ -> package-home move is
    # complete and old-path residue checks are green.
    roadmap=[],
)
