"""The ``reporting`` package's machine-checkable :class:`PackageContract`.

This contract records the reporting-domain cutover boundary for Stage 4 of the
package migration umbrella (#1416, issue #1424): reporting remains the
calculation-over-ledger package and now declares its building blocks with
``units=[Unit(kind=...)]``.

Scope correction (2026-07-06): ``manual_valuation.py`` belongs to the pricing
cutover (#1610). Reporting keeps confidence-tier mapping and report assembly;
pricing owns valuation-observation staleness facts.

Status flip (migration closeout wave 2, #1663): the roadmap's first ACs
(opening-balance gate + the full EPIC-020 framework-reporting set) carry only
``proof_kind`` in ``{exact, property}``, both valid under ``CODE-ONLY`` — so
the package ships ``active``/``CODE-ONLY`` here. The bulk of EPIC-005's ACs
still land in a follow-up commit once the ``services/`` -> package-home move
is complete; this flip does not require that to happen first.
"""

from __future__ import annotations

from common.meta.package_contract import (
    ACRecord,
    Invariant,
    Kind,
    PackageContract,
    Unit,
)

CONTRACT = PackageContract(
    name="reporting",
    status="active",
    tier="CODE-ONLY",
    depends_on=[
        "audit",
        "ledger",
        "portfolio",
        "pricing",
        "extraction",
        "platform",
        "observability",
        "config",
        "reconciliation",
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
        Unit(
            name="get_category_breakdown",
            kind=Kind.DOMAIN_SERVICE,
            module="net_worth.py",
        ),
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
    # The bulk reporting AC transfer from EPIC-005's table lands in a follow-up
    # commit once the full services/ -> package-home move is complete and
    # old-path residue checks are green. Entity names are word-slugs (not
    # numeric groups) since this roadmap started empty in this migration wave.
    roadmap=[
        # ── opening-balance confidence-tier gate (was EPIC-002 AC2.16.4 —
        # EPIC-002 never owned this behavior; it's report assembly, not
        # double-entry posting) ──
        ACRecord(
            id="AC-reporting.opening-balance.1",
            statement=(
                "A HIGH-tier (user_confirmed) balance-sheet line with posted "
                "activity but no recorded opening balance degrades the "
                "report's aggregate confidence_tier to LOW and emits an "
                "opening_balance_warnings entry (type=missing_opening_balance), "
                "so a structurally-incomplete total is never presented as "
                "trusted."
            ),
            # was AC2.16.4
            test=(
                "apps/backend/tests/reporting/test_balance_sheet_opening_balance_gate.py"
                "::test_AC2_16_4_balance_sheet_degrades_tier_and_warns_when_opening_balance_missing"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.opening-balance.2",
            statement=(
                "Once an opening-balance entry is posted for the account that "
                "triggered the degrade, the balance sheet's "
                "opening_balance_warnings clears to empty on the next "
                "generation."
            ),
            # was AC2.16.4
            test=(
                "apps/backend/tests/reporting/test_balance_sheet_opening_balance_gate.py"
                "::test_AC2_16_4_balance_sheet_clears_warning_once_opening_balance_recorded"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.opening-balance.3",
            statement=(
                "The net-worth allocation schedule surfaces the same LOW-tier "
                "degrade and opening_balance_warnings as the balance sheet "
                "when the user needs an opening balance."
            ),
            # was AC2.16.4
            test=(
                "apps/backend/tests/reporting/test_balance_sheet_opening_balance_gate.py"
                "::test_AC2_16_4_net_worth_allocation_surfaces_opening_balance_warning"
            ),
            priority="P1",
            status="done",
        ),
        # ── EPIC-020 framework-aware personal reporting (US-GAAP-like /
        # HK-FRS-like), all proof_kind in {exact, property}: both valid under
        # a CODE-ONLY tier, so this roadmap is tier-flip-ready once EPIC-005's
        # larger AC set (still pending) is assessed the same way ──
        ACRecord(
            id="AC-reporting.framework.1",
            statement=(
                "The framework registry SSOT and EPIC-020 define "
                "`personal_us_gaap_like` and `personal_hkfrs_like`, exclude a "
                "CN/CAS v1 framework, and state that outputs are personal "
                "management reports rather than statutory filings."
            ),
            # was AC20.1.1
            test=(
                "tests/tooling/test_framework_reporting_epic_contract.py"
                "::test_AC20_1_1_framework_registry_defines_us_hk_personal_targets"
            ),
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.lanes.1",
            statement=(
                "The framework-reporting SSOT and EPIC-020 declare the "
                "six-lane fact-forward/target-backward architecture (source "
                "capture, evidence control, canonical ledger, portfolio "
                "subledger, framework policy, report assembly) as mutually "
                "exclusive and collectively covering, with distinct lane "
                "owners."
            ),
            # was AC20.2.1
            test=(
                "tests/tooling/test_framework_reporting_epic_contract.py"
                "::test_AC20_2_1_mece_direction_matrix_declares_distinct_owner_lanes"
            ),
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.target.1",
            statement=(
                "The framework target package contract works backward from "
                "report outputs: it enumerates required statements and "
                "schedules, report line mappings, policy dimensions, "
                "evidence anchors, disclosure requirements, and blocker "
                "conditions before report assembly runs."
            ),
            # was AC20.3.1
            test=(
                "tests/tooling/test_framework_reporting_epic_contract.py"
                "::test_AC20_3_1_framework_target_contract_is_report_output_backward"
            ),
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.policy.1",
            statement=(
                "The v1 policy matrix covers cash and bank accounts, listed "
                "equities/ETFs, funds and money-market products, dividends "
                "and interest, brokerage fees, FX, RSU/ESOP/options, and "
                "property/mortgage/private-manual assets, each across "
                "recognition, measurement, classification, presentation, "
                "and disclosure."
            ),
            # was AC20.4.1
            test=(
                "tests/tooling/test_framework_reporting_epic_contract.py"
                "::test_AC20_4_1_policy_matrix_covers_personal_finance_domains"
            ),
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.policy.2",
            statement=(
                "The framework policy layer is read-only: it consumes "
                "canonical ledger, portfolio facts, and evidence readiness "
                "against the selected framework target without mutating "
                "source records, journal entries, portfolio lots, market "
                "data, or report snapshots, and it does not itself parse "
                "settlements."
            ),
            # was AC20.5.1
            test=(
                "tests/tooling/test_framework_reporting_epic_contract.py"
                "::test_AC20_5_1_policy_layer_is_read_only_between_facts_and_report"
            ),
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.ai.1",
            statement=(
                "An AI measurement/disclosure suggestion affects trusted "
                "output only after becoming a structured field carrying a "
                "source anchor, confidence tier, review state, policy field "
                "name, and accepted value; unreviewed AI suggestions and "
                "incomplete policy fields surface as readiness blocker "
                "codes, and the report package UI requires an explicit "
                "framework selection before loading framework-scoped "
                "output."
            ),
            # was AC20.6.1 (also proven by
            # test_AC20_6_1_ai_suggestions_require_structured_reviewed_policy_fields
            # in tests/tooling/test_framework_reporting_epic_contract.py and by
            # apps/frontend/src/__tests__/personalReportPackagePage.test.tsx)
            test=(
                "apps/backend/tests/reporting/test_framework_package_integration.py"
                "::test_AC20_6_1_ai_suggestions_require_reviewed_policy_fields_for_readiness"
            ),
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.framework.2",
            statement=(
                "The same settlement-and-portfolio fixture drives both "
                "US-like and HK-like personal report packages, producing "
                "framework-specific line mappings, notes bases, source "
                "anchors, export metadata, and readiness blockers from a "
                "single input set."
            ),
            # was AC20.7.1 (also proven by
            # test_AC20_7_1_same_fixture_must_drive_framework_differentiated_reports
            # in tests/tooling/test_framework_reporting_epic_contract.py and the
            # frontend personalReportPackagePage.test.tsx case)
            test=(
                "apps/backend/tests/reporting/test_framework_policy.py"
                "::test_AC20_7_1_same_settlement_fixture_drives_us_hk_report_policy_outputs"
            ),
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.pipeline.1",
            statement=(
                "Every L2 category — each `AssetType` and each "
                "`ManualValuationComponentType` — resolves to a concrete L1 "
                "report line via the framework policy matrix in both "
                "`personal_us_gaap_like` and `personal_hkfrs_like`; a known "
                "category landing in the UNSUPPORTED/gap path fails the "
                "gate (BOND/OTHER regression covered), so report assembly "
                "never improvises a line for a known category."
            ),
            # was AC20.8.1 (also test_AC20_8_1_every_manual_component_maps_to_an_l1_line
            # and test_AC20_8_1_bond_and_other_are_mapped_not_gaps in the same file)
            test=(
                "apps/backend/tests/reporting/test_framework_policy_coverage.py"
                "::test_AC20_8_1_every_asset_type_maps_to_an_l1_line"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-reporting.pipeline.2",
            statement=(
                "EPIC-020 declares the three reporting-pipeline layers "
                "(event→L2, L2→L1, L1→report), each with a locked EPIC-026 "
                "tier and its valid proof obligation, confining LLM "
                "authority to the LLM-LED layer; L1 report assembly "
                "iterates the registered L1 lines, aggregates Decimal "
                "source lines exactly, keeps portfolio cost basis plus "
                "market adjustment on the framework securities L1 line, "
                "and fails closed rather than improvising an unmapped "
                "known source line."
            ),
            # was AC20.9.1 (also
            # test_AC20_9_1_portfolio_cost_basis_and_adjustment_stay_on_securities_l1
            # in the same file, and
            # test_AC20_9_1_reporting_pipeline_declares_layer_authority_tiers
            # in tests/tooling/test_framework_reporting_epic_contract.py)
            test=(
                "apps/backend/tests/reporting/test_l1_registry_aggregation.py"
                "::test_AC20_9_1_framework_balance_sheet_exact_aggregation"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
    ],
)
