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

#1674 contract-honesty audit (2026-07-09): ``config``/``extraction``/
``platform``/``portfolio``/``pricing`` were declared but have zero real
imports under the current ``apps/backend/src/services/reporting`` location —
removed. They are real design intent for the eventual #1666 fold into
``apps/backend/src/reporting/`` (framework-report assembly reading
extraction/portfolio/pricing facts through platform's readiness port); re-add
each with its first real import, not before.
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
        "observability",
        # portfolio: the market-value adjustment lines read holdings via the
        # published PortfolioService (was services.portfolio before #1643).
        "portfolio",
        "pricing",
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
        # ── DRY/SSOT simplification (EPIC-025) ──
        ACRecord(
            id="AC-reporting.dry-ssot.1",
            statement=(
                "Pure reporting math (money quantization, accounting sign "
                "rules, period boundaries, income-bucket classification) is "
                "provided by `services.reporting_calc` and re-used by "
                "`services.reporting`; the balance-sheet equation and "
                "report totals are unchanged."
            ),
            # was AC25.1.1
            test=(
                "apps/backend/tests/reporting/test_reporting_calc_extraction.py"
                "::test_reporting_calc_extraction"
            ),
            priority="P1",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.dry-ssot.2",
            statement=(
                "Shared reporting fixtures (standard chart of accounts, "
                "golden dashboard scenario, standard FX rates) are provided "
                "by a single `tests/reporting/_report_fixtures` module and "
                "reused, with duplicate per-file `test_user_id` fixtures "
                "removed; existing AC traceability is preserved."
            ),
            # was AC25.4.1
            test=(
                "apps/backend/tests/reporting/test_report_fixtures_shared.py"
                "::test_report_fixtures_shared"
            ),
            priority="P1",
            status="done",
            proof_kind="exact",
        ),
        # ── export-envelope (EPIC-006 AC6.33.5/.6/.8/.9, closeout wave 3,
        # #1416) — ExportStreamEnvelope (apps/backend/src/schemas/streaming.py)
        # is the reporting/export surface of the typed streaming contract; the
        # chat-side envelope already migrated to common/advisor/contract.py's
        # roadmap (AC-advisor.envelope.*) ──
        ACRecord(
            id="AC-reporting.export-envelope.1",
            statement=(
                "ExportStreamEnvelope declares the wire media type and builds "
                "an attachment Content-Disposition header carrying the "
                "envelope's filename."
            ),
            test=(
                "apps/backend/tests/ai/test_streaming_contract.py"
                "::test_AC6_33_5_export_envelope_builds_attachment_headers"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.export-envelope.2",
            statement=(
                "ExportStreamEnvelope rejects a media type outside the "
                "declared wire set (e.g. application/pdf) at construction."
            ),
            test=(
                "apps/backend/tests/ai/test_streaming_contract.py"
                "::test_AC6_33_6_export_envelope_rejects_unknown_media_type"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.export-envelope.3",
            statement=(
                "GET /reports/export's response media type and "
                "Content-Disposition header equal what ExportStreamEnvelope "
                "would produce for the same filename."
            ),
            test=(
                "apps/backend/tests/reporting/test_reports_router.py"
                "::test_AC6_33_8_export_response_matches_typed_envelope"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.export-envelope.4",
            statement=(
                "ExportStreamEnvelope rejects a filename carrying CR/LF, a "
                "double-quote, a semicolon, or a path separator, since the "
                "filename is interpolated into the Content-Disposition header "
                "and each of those characters would break out of it or inject "
                "a header."
            ),
            test=(
                "apps/backend/tests/ai/test_streaming_contract.py"
                "::test_AC6_33_9_export_envelope_rejects_unsafe_filename"
            ),
            priority="P0",
            status="done",
        ),
        # ── group balance-sheet: balance-sheet generation (was EPIC-005
        # AC5.1.1-4, migration closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.balance-sheet.1",
            statement=(
                "The generated balance sheet satisfies the accounting equation: assets = "
                "liabilities + equity (net income included)."
            ),
            # was AC5.1.1
            test="apps/backend/tests/reporting/test_reporting.py::test_balance_sheet_equation",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.balance-sheet.2",
            statement=(
                "FX unrealized gain is calculated for foreign-currency balances on the balance "
                "sheet."
            ),
            # was AC5.1.2
            test=(
                "apps/backend/tests/reporting/test_reporting_fx.py"
                "::test_fx_unrealized_gain_calculation"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.balance-sheet.3",
            statement=(
                "Multi-currency account balances aggregate into the base reporting currency on "
                "the balance sheet."
            ),
            # was AC5.1.3
            test=(
                "apps/backend/tests/reporting/test_reporting_fx.py"
                "::test_multi_currency_aggregation"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.balance-sheet.4",
            statement="GET /reports/balance-sheet returns the generated balance sheet payload.",
            # was AC5.1.4
            test="apps/backend/tests/reporting/test_reports_router.py::test_balance_sheet_endpoint",
            priority="P0",
            status="done",
        ),
        # ── group income-statement (was EPIC-005 AC5.2.1-3, migration
        # closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.income-statement.1",
            statement="The income statement computes net income as income minus expenses.",
            # was AC5.2.1
            test=(
                "apps/backend/tests/reporting/test_reporting.py"
                "::test_income_statement_calculation"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.income-statement.2",
            statement="The income statement includes comprehensive income from FX effects.",
            # was AC5.2.2
            test=(
                "apps/backend/tests/reporting/test_reporting_fx.py"
                "::test_income_statement_comprehensive_income"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.income-statement.3",
            statement=(
                "The income statement rejects an invalid date range (start after end) with a "
                "domain error."
            ),
            # was AC5.2.3
            test=(
                "apps/backend/tests/reporting/test_reporting.py"
                "::test_income_statement_invalid_range"
            ),
            priority="P1",
            status="done",
        ),
        # ── group cash-flow: cash-flow statement + trend/breakdown endpoints
        # (was EPIC-005 AC5.3.1-5, migration closeout continuation,
        # #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.cash-flow.1",
            statement=(
                "The cash-flow statement is generated with operating, investing, and financing "
                "sections."
            ),
            # was AC5.3.1
            test="apps/backend/tests/reporting/test_reporting.py::test_cash_flow_statement",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.cash-flow.2",
            statement=(
                "A period with no cash movement generates an empty (zeroed) cash-flow "
                "statement, not an error."
            ),
            # was AC5.3.2
            test="apps/backend/tests/reporting/test_reporting.py::test_cash_flow_empty_period",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.cash-flow.3",
            statement=(
                "GET /reports/trend returns account trend data across different period "
                "granularities."
            ),
            # was AC5.3.3
            test="apps/backend/tests/api/test_reports_router.py::test_account_trend_with_period",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.cash-flow.4",
            statement="GET /reports/breakdown returns the category breakdown.",
            # was AC5.3.4
            test="apps/backend/tests/api/test_reports_router.py::test_category_breakdown_success",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.cash-flow.5",
            statement="GET /reports/breakdown honors the requested period parameter.",
            # was AC5.3.5
            test=(
                "apps/backend/tests/api/test_reports_router.py"
                "::test_category_breakdown_with_period"
            ),
            priority="P1",
            status="done",
        ),
        # ── group fx: multi-currency conversion fallbacks (was EPIC-005
        # AC5.4.1-4, migration closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.fx.1",
            statement=(
                "Report FX conversion falls back through the documented rate-resolution chain."
            ),
            # was AC5.4.1
            test="apps/backend/tests/reporting/test_reporting_fx.py::test_reporting_fx_fallbacks",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fx.2",
            statement=(
                "Balance-sheet net income uses the FX fallback path when a direct rate is "
                "missing."
            ),
            # was AC5.4.2
            test=(
                "apps/backend/tests/reporting/test_reporting_fx.py"
                "::test_balance_sheet_net_income_fx_fallback"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fx.3",
            statement=(
                "Reports lazily resolve a missing cross rate (e.g. HKD/SGD) from stored bridge "
                "rates."
            ),
            # was AC5.4.3
            test=(
                "apps/backend/tests/reporting/test_reporting_fx.py"
                "::test_reports_lazy_resolve_missing_hkd_sgd_from_bridge_rates"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fx.4",
            statement=(
                "Missing report FX rates produce explicit partial warnings for the "
                "unconvertible currency instead of aborting the whole aggregation."
            ),
            # was AC5.4.4
            test=(
                "apps/backend/tests/reporting/test_reporting_fx_fallbacks.py"
                "::test_aggregate_balances_missing_fx_skips_unconvertible_currency_with_warning"
            ),
            priority="P0",
            status="done",
        ),
        # ── group errors: report error handling + auth boundary (was EPIC-005
        # AC5.5.1-5, migration closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.errors.1",
            statement="Report-generation failures surface as structured router errors.",
            # was AC5.5.1
            test=(
                "apps/backend/tests/reporting/test_reports_errors.py"
                "::test_reports_router_errors_extended"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.errors.2",
            statement=(
                "Each reports endpoint maps a ReportError to a structured HTTP error response "
                "(TestReportsRouterErrors suite; representative test cited)."
            ),
            # was AC5.5.2
            test=(
                "apps/backend/tests/reporting/test_reports_router_errors.py"
                "::test_balance_sheet_report_error"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.errors.3",
            statement="Unauthenticated clients cannot access the reports endpoints.",
            # was AC5.5.3
            test="apps/backend/tests/api/test_reports_router.py::test_unauthenticated_access",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.errors.4",
            statement=(
                "The reports router endpoints respond successfully for an authenticated user "
                "(representative endpoint test cited)."
            ),
            # was AC5.5.4
            test=(
                "apps/backend/tests/reporting/test_reports_router.py"
                "::test_income_statement_endpoint"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.errors.5",
            statement=(
                "GET /reports/{report_type}/snapshots returns the user's persisted report "
                "snapshots."
            ),
            # was AC5.5.5
            test=(
                "apps/backend/tests/api/test_reports_router.py"
                "::test_list_report_snapshots_returns_created_snapshots"
            ),
            priority="P1",
            status="done",
        ),
        # ── group kpis: dashboard/report KPI surfaces + FX guardrails (was
        # EPIC-005 AC5.6.4-5 and AC5.6.7-11 — AC5.6.4's frontend dashboard-card
        # half stays in EPIC-005; migration closeout continuation,
        # #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.kpis.1",
            statement=(
                "The annualized income KPI endpoint groups the last 12 months of income; "
                "calculation ownership stays with AC11.8.1."
            ),
            # was AC5.6.4 (backend half)
            test=(
                "apps/backend/tests/reporting/test_income_annualized_router.py"
                "::test_annualized_income_endpoint_groups_last_12_month_income"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.kpis.2",
            statement=(
                "Unrealized P&L is reflected in balance-sheet equity (golden dashboard fixture "
                "asserts exact totals)."
            ),
            # was AC5.6.5
            test=(
                "apps/backend/tests/reporting/test_reporting.py"
                "::test_reporting_dashboard_fixture_exact_totals"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.kpis.3",
            statement=(
                "Report output lists the currencies that used the average-rate spot fallback."
            ),
            # was AC5.6.7
            test=(
                "apps/backend/tests/reporting/test_reporting_fx_revaluation_integration.py"
                "::test_income_statement_includes_average_rate_fallback_warning"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.kpis.4",
            statement="Account trend raises when a prefetched non-base FX rate is missing.",
            # was AC5.6.8
            test=(
                "apps/backend/tests/reporting/test_reporting_extreme_fallbacks.py"
                "::test_account_trend_raises_when_prefetched_rate_missing"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.kpis.5",
            statement="Category breakdown raises when a prefetched non-base FX rate is missing.",
            # was AC5.6.9
            test=(
                "apps/backend/tests/reporting/test_reporting_extreme_fallbacks.py"
                "::test_category_breakdown_raises_when_prefetched_rate_missing"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.kpis.6",
            statement="Cash flow raises when the start-date non-base FX rate is missing.",
            # was AC5.6.10
            test=(
                "apps/backend/tests/reporting/test_reporting_extreme_fallbacks.py"
                "::test_cash_flow_raises_when_start_date_rate_missing"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.kpis.7",
            statement=(
                "Cash flow raises when the end-date FX rate is missing, propagating "
                "FxRateError."
            ),
            # was AC5.6.11
            test=(
                "apps/backend/tests/reporting/test_reporting_extreme_fallbacks.py"
                "::test_cash_flow_raises_when_end_date_rate_missing"
            ),
            priority="P1",
            status="done",
        ),
        # ── group package-investment: investment-performance section consumption
        # (was EPIC-005 AC5.8.1's backend contract half — the frontend render
        # and post-merge journey proofs stay in EPIC-005; migration closeout
        # continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.package-investment.1",
            statement=(
                "The personal report package defines the investment_performance section as a "
                "consumer of the EPIC-017 schedule API, preserving source_links and notes."
            ),
            # was AC5.8.1 (backend half)
            test=(
                "tests/tooling/test_investment_performance_report_contract.py"
                "::test_AC5_8_1_personal_report_package_consumes_investment_schedule_contract"
            ),
            priority="P0",
            status="done",
        ),
        # ── group package-contract: personal report package API contract (was
        # EPIC-005 AC5.9.1-2 — the frontend rows AC5.9.3-4 stay in EPIC-005;
        # migration closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.package-contract.1",
            statement=(
                "The package contract endpoint defines the required section IDs, labels, "
                "owners, and source endpoints."
            ),
            # was AC5.9.1
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC5_9_1_package_contract_endpoint_defines_required_sections"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.package-contract.2",
            statement=(
                "The package contract exposes Decimal-safe total fields and explicit "
                "period/as-of semantics."
            ),
            # was AC5.9.2
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC5_9_2_package_contract_marks_decimal_totals_and_period_semantics"
            ),
            priority="P0",
            status="done",
        ),
        # ── group logic-audit: financial statement logic audit fixes (was
        # EPIC-005 AC5.10.1-2, migration closeout continuation,
        # #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.logic-audit.1",
            statement=(
                "Cash-flow beginning cash, ending cash, and net cash flow use cumulative cash "
                "balances."
            ),
            # was AC5.10.1
            test=(
                "apps/backend/tests/reporting/test_financial_logic_audit.py"
                "::test_AC5_10_1_cash_flow_uses_cumulative_cash_balances"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.logic-audit.2",
            statement=(
                "Cash-flow operating, investing, and financing totals preserve inflow/outflow "
                "signs."
            ),
            # was AC5.10.2
            test=(
                "apps/backend/tests/reporting/test_financial_logic_audit.py"
                "::test_AC5_10_2_cash_flow_activity_totals_preserve_signs"
            ),
            priority="P0",
            status="done",
        ),
        # ── group package-annualized: annualized income schedule consumption
        # (was EPIC-005 AC5.11.1 and AC5.11.3 — the frontend row AC5.11.2 stays
        # in EPIC-005; migration closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.package-annualized.1",
            statement=(
                "The package contract marks annualized_income_long_term ready and points at the "
                "schedule endpoint."
            ),
            # was AC5.11.1
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC5_11_1_package_contract_marks_annualized_schedule_ready"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.package-annualized.2",
            statement=(
                "The annualized income package schedule converts mixed-currency income and "
                "restricted totals into one reporting currency."
            ),
            # was AC5.11.3
            test=(
                "apps/backend/tests/reporting/test_annualized_income_schedule.py"
                "::test_AC5_11_3_AC11_11_3_annualized_schedule_converts_mixed_currency_totals"
            ),
            priority="P0",
            status="done",
        ),
        # ── group package-notes: notes and disclosure basis (was EPIC-005
        # AC5.12.1-2 and AC5.12.4 — the frontend row AC5.12.3 stays in
        # EPIC-005; migration closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.package-notes.1",
            statement=(
                "The package notes endpoint returns the required note IDs, owner EPICs, source "
                "states, and non-compliance wording."
            ),
            # was AC5.12.1
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC5_12_1_package_notes_endpoint_returns_required_note_taxonomy"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.package-notes.2",
            statement="The package contract marks notes ready and points at the notes endpoint.",
            # was AC5.12.2
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC5_12_2_package_contract_marks_notes_ready"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.package-notes.3",
            statement=(
                "The post-merge package proof asserts the notes endpoint, required note IDs, "
                "and non-compliance wording."
            ),
            # was AC5.12.4
            test=(
                "tests/e2e/test_personal_financial_report_package.py"
                "::test_personal_financial_report_package_post_merge_journey"
            ),
            priority="P0",
            status="done",
        ),
        # ── group package-traceability: source-ledger-report appendix (was
        # EPIC-005 AC5.13.1-2 and AC5.13.4-5 — the frontend row AC5.13.3 stays
        # in EPIC-005; migration closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.package-traceability.1",
            statement=(
                "The package traceability endpoint returns source-to-ledger anchors per report "
                "line."
            ),
            # was AC5.13.1
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC5_13_1_package_traceability_endpoint_returns_section_line_anchors"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.package-traceability.2",
            statement=(
                "The traceability appendix exposes explicit completeness states where anchors "
                "are unavailable."
            ),
            # was AC5.13.2
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC5_13_2_package_traceability_declares_completeness_warnings"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.package-traceability.3",
            statement=(
                "The post-merge package proof fails trusted totals without source/ledger "
                "anchors or explicit manual inputs."
            ),
            # was AC5.13.4
            test=(
                "tests/e2e/test_personal_financial_report_package.py"
                "::test_personal_financial_report_package_post_merge_journey"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.package-traceability.4",
            statement=(
                "The package traceability endpoint returns current-user dynamic source "
                "identifiers and excludes unrelated-user anchors."
            ),
            # was AC5.13.5
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC5_13_5_package_traceability_returns_dynamic_current_user_identifiers"
            ),
            priority="P0",
            status="done",
        ),
        # ── group integration: backend reporting integration journey (was
        # EPIC-005 AC5.15.1, migration closeout continuation,
        # #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.integration.1",
            statement=(
                "Multi-currency posted entries generate balanced balance-sheet, "
                "income-statement, and cash-flow reports in the base currency."
            ),
            # was AC5.15.1
            test=(
                "apps/backend/tests/integration/test_reporting_e2e.py"
                "::test_AC5_15_1_multicurrency_reporting_cycle_reconciles_bs_is_cf"
            ),
            priority="P0",
            status="done",
        ),
        # ── group trust-signals: report trust signals + restricted-asset
        # defaults (was EPIC-005 AC5.16.1-2 backend halves and AC5.16.4 — the
        # frontend halves and AC5.16.3 stay in EPIC-005; migration closeout
        # continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.trust-signals.1",
            statement=(
                "The balance sheet defaults restricted holdings to excluded and exposes an "
                "include toggle."
            ),
            # was AC5.16.1 (backend half)
            test=(
                "apps/backend/tests/reporting/test_reports_router.py"
                "::test_AC5_16_1_balance_sheet_defaults_to_excluding_restricted_holdings"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.trust-signals.2",
            statement=(
                "Report responses preserve backend fx_warnings so pages never silently render "
                "partial totals."
            ),
            # was AC5.16.2 (backend half)
            test=(
                "apps/backend/tests/reporting/test_reports_router.py"
                "::test_AC5_16_2_cash_flow_response_preserves_fx_warnings"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.trust-signals.3",
            statement=(
                "Package traceability lines expose source classes, proof level, anchor count, "
                "and blocker codes for report-line confidence review."
            ),
            # was AC5.16.4
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC5_13_1_package_traceability_endpoint_returns_section_line_anchors"
            ),
            priority="P0",
            status="done",
        ),
        # ── group csv-export: authenticated report CSV exports (was EPIC-005
        # AC5.17.1's backend half — the frontend apiDownload half and AC5.17.2
        # stay in EPIC-005; migration closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.csv-export.1",
            statement=(
                "The backend CSV export supports cash-flow reports with date-range and currency "
                "filters."
            ),
            # was AC5.17.1 (backend half)
            test=(
                "apps/backend/tests/reporting/test_reports_router.py"
                "::test_AC5_17_1_cash_flow_export_returns_csv"
            ),
            priority="P0",
            status="done",
        ),
        # ── group confidence: per-node confidence tier on balance-sheet
        # payloads (was EPIC-005 AC5.18.1-2, migration closeout continuation,
        # #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.confidence.1",
            statement=(
                "Each balance-sheet line carries the worst-input confidence tier of its "
                "contributing journal entries."
            ),
            # was AC5.18.1
            test=(
                "apps/backend/tests/reporting/test_balance_sheet_confidence.py"
                "::test_AC5_18_1_lines_carry_worst_input_confidence_tier"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.confidence.2",
            statement=(
                "The Net Worth aggregate rolls up to the worst-input tier across rated lines, "
                "and is null when nothing is rated."
            ),
            # was AC5.18.2
            test=(
                "apps/backend/tests/reporting/test_balance_sheet_confidence.py"
                "::test_AC5_18_2_net_worth_rolls_up_to_worst_input_tier"
            ),
            priority="P1",
            status="done",
        ),
        # ── group package-snapshot: durable package snapshot artifact (was
        # EPIC-005 AC5.19.1-3 — the frontend row AC5.19.4 stays in EPIC-005;
        # migration closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.package-snapshot.1",
            statement=(
                "POST /api/reports/package/generate creates an immutable package snapshot; "
                "blocked readiness may generate only a draft while ready readiness generates "
                "trusted output."
            ),
            # was AC5.19.1
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC5_19_1_package_generate_creates_draft_or_trusted_snapshot"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.package-snapshot.2",
            statement=(
                "Package snapshot list/reopen endpoints are user-scoped and reopening returns "
                "the original payload after live inputs change."
            ),
            # was AC5.19.2
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC5_19_2_package_snapshot_get_is_user_scoped_and_immutable"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.package-snapshot.3",
            statement=(
                "Package JSON and CSV downloads are derived from a saved snapshot rather than "
                "recalculating live data."
            ),
            # was AC5.19.3
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC5_19_3_package_snapshot_exports_are_snapshot_derived"
            ),
            priority="P0",
            status="done",
        ),
        # ── group year-scale: year-scale reporting validation (was EPIC-005
        # AC5.20.1, migration closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.year-scale.1",
            statement=(
                "At a full year's transaction volume the three statements tie out and generate "
                "within a wall-clock backstop, guarding against a silent O(n^2) regression."
            ),
            # was AC5.20.1
            test=(
                "apps/backend/tests/reporting/test_year_scale_reporting.py"
                "::test_AC5_20_year_scale_reporting_ties_out_within_budget"
            ),
            priority="P1",
            status="done",
        ),
        # ── group income-typed: income module typed currency + typed
        # intermediates (was EPIC-005 AC5.32.1-6, migration closeout
        # continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.income-typed.1",
            statement=(
                "AnnualizedIncomeResponse.currency is the shared typed CurrencyCode (validated "
                "length + normalized), not a soft str."
            ),
            # was AC5.32.1
            test=(
                "apps/backend/tests/reporting/test_income_typed_currency.py"
                "::test_AC5_32_1_currency_code_type_validates_and_normalizes"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.income-typed.2",
            statement=(
                "Income totals accumulate in a typed AnnualizedIncomeTotals Decimal "
                "intermediate, not a string-keyed dict."
            ),
            # was AC5.32.2
            test=(
                "apps/backend/tests/reporting/test_income_typed_currency.py"
                "::test_AC5_32_2_annualized_income_totals_is_typed_intermediate"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.income-typed.3",
            statement=(
                "resolve_line_currency centralizes the line/account/base currency fallback + "
                "normalization."
            ),
            # was AC5.32.3
            test=(
                "apps/backend/tests/reporting/test_income_typed_currency.py"
                "::test_AC5_32_3_resolve_line_currency_uses_canonical_fallback_chain"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.income-typed.4",
            statement=(
                "An explicit FX-failure response model (FxConversionErrorResponse) is declared "
                "for the income endpoint."
            ),
            # was AC5.32.4
            test=(
                "apps/backend/tests/reporting/test_income_typed_currency.py"
                "::test_AC5_32_4_fx_conversion_error_response_model_declared"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.income-typed.5",
            statement=(
                "Currency normalization is a single shared helper (normalize_currency_code), "
                "not duplicated strip/upper."
            ),
            # was AC5.32.5
            test=(
                "apps/backend/tests/reporting/test_income_typed_currency.py"
                "::test_AC5_32_5_normalize_currency_code_is_shared_helper"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.income-typed.6",
            statement=(
                "The income endpoint normalizes a soft (lower-case) base-currency setting in "
                "its response."
            ),
            # was AC5.32.6
            test=(
                "apps/backend/tests/reporting/test_income_typed_currency.py"
                "::test_AC5_32_6_endpoint_returns_normalized_currency_for_soft_base_config"
            ),
            priority="P2",
            status="done",
        ),
        # ── group snapshots-typed: report snapshots typed contract (was
        # EPIC-005 AC5.36.1-2, migration closeout continuation,
        # #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.snapshots-typed.1",
            statement=(
                "GET /reports/{report_type}/snapshots rejects an unknown report_type with 422."
            ),
            # was AC5.36.1
            test=(
                "apps/backend/tests/api/test_typed_contract_sweep.py"
                "::test_AC5_36_1_report_snapshots_unknown_type_returns_422"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.snapshots-typed.2",
            statement="A valid report_type returns a typed list[ReportSnapshotSummary] response.",
            # was AC5.36.2
            test=(
                "apps/backend/tests/api/test_typed_contract_sweep.py"
                "::test_AC5_36_2_report_snapshots_valid_type_returns_typed_list"
            ),
            priority="P2",
            status="done",
        ),
        # ── group journeys: reporting core-journey E2E (was EPIC-008
        # AC8.6.1-4, migration closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.journeys.1",
            statement="The core-journey E2E views the balance sheet end to end.",
            # was AC8.6.1
            test="apps/backend/tests/e2e/test_core_journeys.py::test_balance_sheet_report",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.journeys.2",
            statement="The core-journey E2E views the income statement end to end.",
            # was AC8.6.2
            test="apps/backend/tests/e2e/test_core_journeys.py::test_income_statement_report",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.journeys.3",
            statement="The core-journey E2E views the cash-flow report end to end.",
            # was AC8.6.3
            test="apps/backend/tests/e2e/test_core_journeys.py::test_cash_flow_report",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.journeys.4",
            statement="The core-journey E2E navigates every reports endpoint.",
            # was AC8.6.4
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_report_navigation_all_endpoints"
            ),
            priority="P1",
            status="done",
        ),
        # ── group full-year: full-year statement-to-report acceptance (was
        # EPIC-008 AC8.15.1-2, migration closeout continuation,
        # #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.full-year.1",
            statement=(
                "Multi-month CSV statements parse, approve under the balance-chain guard, "
                "auto-post, and the assembled period reports tie out end to end."
            ),
            # was AC8.15.1
            test=(
                "apps/backend/tests/integration/test_full_year_statement_to_report_e2e.py"
                "::test_AC8_15_1_full_year_statement_to_report_ties_out"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.full-year.2",
            statement=(
                "A high-confidence balance-validated bank statement with no pre-selected "
                "account auto-creates+links its asset account, reaches APPROVED, and auto-posts "
                "to the ledger."
            ),
            # was AC8.15.2
            test=(
                "apps/backend/tests/integration/test_bank_statement_auto_account_post.py"
                "::test_AC8_15_2_bank_statement_auto_creates_account_and_posts_without_manual_mapping"
            ),
            priority="P1",
            status="done",
        ),
        # ── group augmentation: augmentation-layer report integrity (was
        # EPIC-008 AC8.16.1-2, migration closeout continuation,
        # #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.augmentation.1",
            statement=(
                "A low-confidence ledger input and a superseded manual valuation both reach the "
                "report correctly: the equation holds, the low-confidence line carries the "
                "worst-input tier, and the superseded valuation is excluded."
            ),
            # was AC8.16.1
            test=(
                "apps/backend/tests/integration/test_augmentation_seam_e2e.py"
                "::test_AC8_16_1_augmentation_seam_excludes_superseded_and_surfaces_confidence"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.augmentation.2",
            statement=(
                "A report aggregates only the requesting user's facts: another user's accounts "
                "never appear and never inflate a total."
            ),
            # was AC8.16.2
            test=(
                "apps/backend/tests/integration/test_cross_user_report_isolation_e2e.py"
                "::test_AC8_16_2_reports_exclude_other_users_entries"
            ),
            priority="P1",
            status="done",
        ),
        # ── group net-worth-components: retirement/benefit assets in reports
        # (was EPIC-011 AC11.20.1-2 — the frontend row AC11.20.3 stays in
        # EPIC-011; migration closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.net-worth-components.1",
            statement=(
                "Retirement accounts, social-security personal balances, legacy CPF, and "
                "insurance cash value default to restricted assets and contribute to full "
                "balance-sheet assets."
            ),
            # was AC11.20.1
            test=(
                "apps/backend/tests/reporting/test_reporting_net_worth_components.py"
                "::test_AC11_20_1_retirement_and_benefit_assets_are_restricted_assets_in_balance_sheet"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.net-worth-components.2",
            statement=(
                "Net-worth allocation groups retirement and benefit balances under the "
                "retirement-and-benefit asset class."
            ),
            # was AC11.20.2
            test=(
                "apps/backend/tests/reporting/test_reporting_net_worth_components.py"
                "::test_AC11_20_2_net_worth_allocation_groups_retirement_and_benefit_assets"
            ),
            priority="P1",
            status="done",
        ),
        # ── group layer3: Layer 3/4 read integration (was EPIC-018 AC18.4.1-2
        # and AC18.4.4 — AC18.4.3 is extraction-owned and stays; migration
        # closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.layer3.1",
            statement=(
                "The income statement's classification coverage reads Layer 3 APPLIED "
                "TransactionClassification rows joined to their category accounts — the "
                "report-side read of Layer 3 classifications."
            ),
            # was AC18.4.1
            test=(
                "apps/backend/tests/reporting/test_reporting_net_worth_components.py"
                "::test_income_statement_includes_applied_classification_breakdown"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.layer3.2",
            statement=(
                "ReportSnapshot (Layer 4) rows are generated and queryable via the reports "
                "snapshots API."
            ),
            # was AC18.4.2
            test=(
                "apps/backend/tests/api/test_reports_router.py"
                "::test_list_report_snapshots_returns_created_snapshots"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.layer3.3",
            statement=(
                "Income statement payloads include the applied Layer 3 classification coverage "
                "breakdown."
            ),
            # was AC18.4.4
            test=(
                "apps/backend/tests/reporting/test_reporting_net_worth_components.py"
                "::test_income_statement_includes_applied_classification_breakdown"
            ),
            priority="P1",
            status="done",
        ),
        # ── group north-star: North-Star confidence metric (was EPIC-018
        # AC18.12.1-4, migration closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.north-star.1",
            statement=(
                "The low-confidence proportion is the deterministic LOW-tier share of "
                "posted/reconciled journal entries, with a full tier breakdown and a defined "
                "zero on an empty ledger."
            ),
            # was AC18.12.1
            test=(
                "apps/backend/tests/metrics/test_confidence_north_star_metric.py"
                "::test_AC18_12_1_low_confidence_proportion_and_tier_breakdown_are_deterministic"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.north-star.2",
            statement=(
                "The metric is recorded as an append-only series — snapshots accumulate "
                "newest-first and are never overwritten — so the trend is observable."
            ),
            # was AC18.12.2
            test=(
                "apps/backend/tests/metrics/test_confidence_north_star_metric.py"
                "::test_AC18_12_2_metric_is_recorded_as_append_only_series_showing_the_trend"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.north-star.3",
            statement=(
                "The current metric and its recorded series are exposed read-only via the API."
            ),
            # was AC18.12.3
            test=(
                "apps/backend/tests/metrics/test_confidence_north_star_metric.py"
                "::test_AC18_12_3_north_star_endpoint_returns_current_and_series"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.north-star.4",
            statement=(
                "A North-Star snapshot is recorded when a report package is generated, and on "
                "demand via a POST endpoint, so the trend accumulates in production."
            ),
            # was AC18.12.4
            test=(
                "apps/backend/tests/metrics/test_confidence_north_star_metric.py"
                "::test_AC18_12_4_post_records_a_snapshot_into_the_series"
            ),
            priority="P1",
            status="done",
        ),
        # ── group readiness: report readiness + blocker state (was EPIC-019
        # AC19.5.1-3, AC19.5.6-7 and AC19.7.1 — the frontend rows AC19.5.4-5
        # stay in EPIC-019; migration closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.readiness.1",
            statement=(
                "The personal report package exposes a user-scoped readiness endpoint returning "
                "deterministic state, action link, blocker count, and source summary."
            ),
            # was AC19.5.1
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC19_5_1_package_readiness_returns_draft_for_empty_user"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.readiness.2",
            statement=(
                "Blocked package readiness lists exact blocker categories across parsing, "
                "review, balance, reconciliation, consistency, Processing balance, and source "
                "coverage."
            ),
            # was AC19.5.2
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC19_5_2_package_readiness_lists_actionable_blockers"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.readiness.3",
            statement=(
                "Package readiness deterministically promotes through draft, processing, "
                "blocked, ready, generated, and stale based on source state and snapshot "
                "freshness."
            ),
            # was AC19.5.3
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC19_5_3_package_readiness_state_priority_and_snapshot_freshness"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.readiness.4",
            statement=(
                "Package readiness fails deterministically when duplicate Processing system "
                "accounts would make blockers non-deterministic."
            ),
            # was AC19.5.6
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC19_5_6_package_readiness_rejects_duplicate_processing_accounts"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.readiness.5",
            statement=(
                "Package readiness converts Processing Account journal lines into the base "
                "reporting currency before deciding whether the in-transit balance nets to "
                "zero."
            ),
            # was AC19.5.7
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC19_5_7_package_readiness_converts_processing_balance_before_zero_check"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.readiness.6",
            statement=(
                "Report readiness evaluates framework-specific evidence blockers from the "
                "framework policy layer before marking US/HK personal reports trusted."
            ),
            # was AC19.7.1
            test=(
                "apps/backend/tests/reporting/test_framework_package_integration.py"
                "::test_AC19_7_1_readiness_consumes_framework_specific_evidence_blockers"
            ),
            priority="P0",
            status="done",
        ),
        # ── group source-trust: source trust readiness summary (was EPIC-019
        # AC19.9.1 — the frontend row AC19.9.2 stays in EPIC-019; migration
        # closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.source-trust.1",
            statement=(
                "Package readiness returns a source-trust summary by source class: "
                "deterministic PR proof availability, post-merge LLM/OCR coverage, "
                "manual-trusted classes, gaps, and blocker codes."
            ),
            # was AC19.9.1
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC19_9_1_package_readiness_reports_source_trust_summary"
            ),
            priority="P0",
            status="done",
        ),
        # ── group source-anchors: typed package source anchors (was EPIC-019
        # AC19.10.1, migration closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.source-anchors.1",
            statement=(
                "Package traceability resolves journal source IDs to typed source anchors and "
                "blocks unknown source IDs instead of presenting them as statement "
                "transactions."
            ),
            # was AC19.10.1
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC19_10_1_unknown_journal_source_ids_are_not_reported_as_statement_transactions"
            ),
            priority="P0",
            status="done",
        ),
        # ── group lineage: account lineage drill-down (was EPIC-022 AC22.3.3
        # and AC22.7.1's backend half — AC22.7.1's frontend drawer half stays
        # in EPIC-022; migration closeout continuation, #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.lineage.1",
            statement=(
                "GET /api/reports/account-lineage returns the user-scoped posted/reconciled "
                "journal lines contributing to an account's balance, each with a journal_line "
                "evidence anchor and Decimal-safe signed amounts."
            ),
            # was AC22.3.3
            test=(
                "apps/backend/tests/reporting/test_account_lineage.py"
                "::test_AC22_3_3_account_lineage_returns_posted_contributing_lines"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.lineage.2",
            statement=(
                "Each cash-flow line carries its account anchor (account_id) so a cash-flow "
                "amount can drill down to the account's contributing journal lines."
            ),
            # was AC22.7.1 (backend half)
            test=(
                "apps/backend/tests/reporting/test_reporting.py"
                "::test_reporting_dashboard_fixture_exact_totals"
            ),
            priority="P1",
            status="done",
        ),
        # ── group provenance: normalized report-line provenance (was EPIC-022
        # AC22.13.1's reporting share — the pricing share is
        # AC-pricing.provenance.1 and the portfolio share is
        # AC-portfolio.provenance.2; migration closeout continuation,
        # #1663 / #1716) ──
        ACRecord(
            id="AC-reporting.provenance.1",
            statement=(
                "Report amount lines expose the normalized provenance enum "
                "(imported/manual/derived) when the source basis is known, and stay unlabeled "
                "instead of guessing."
            ),
            # was AC22.13.1 (reporting share)
            test=(
                "apps/backend/tests/reporting/test_reporting.py"
                "::test_AC22_13_1_report_amount_lines_expose_normalized_provenance"
            ),
            priority="P1",
            status="done",
        ),
    ],
)
