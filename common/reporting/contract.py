"""Machine-checkable PackageContract for ``reporting``."""

from __future__ import annotations

from common.meta.package_contract import (
    ContextScope,
    GovernanceGuarantee,
    GovernanceInitiative,
    PackageContract,
    acs,
    concepts,
    invs,
    rels,
    units,
)

CONTRACT = PackageContract(
    name="reporting",
    status="active",
    tier="CODE-ONLY",
    depends_on="""
audit extraction ledger observability platform portfolio pricing reconciliation
""".split(),
    roles="base extension data".split(),
    implementations={"be": "apps/backend/src/reporting", "fe": None},
    context=ContextScope(
        purpose="Own deterministic financial report assembly, framework disclosure.",
        in_scope=[
            "Financial statement and net-worth calculation views.",
            "ReportSnapshot, report-line, framework-policy, readiness.",
            "Report-package assembly and traceability of the exact facts a report freezes.",
        ],
        out_of_scope=[
            "Source-document parsing, ledger posting, position accounting, matching, or valuation resolution.",
            "Shared financial value/assurance ownership and generic telemetry or persistence substrate.",
            "Cross-domain workflow execution and user-facing delivery routing.",
        ],
    ),
    relationships=rels(
        "reporting",
        """
audit|published-language|Uses audit monetary, source-type.
extraction|projection|Reads statement contributions and source-fact projections.
ledger|projection|Reads posted ledger and account projections.
observability|published-language|Uses published safe logging and error-identification language for report generation diagnostics.
platform|composition|Uses platform persistence mixins and request-error helpers.
portfolio|projection|Reads portfolio performance and holdings projections for report schedules.
pricing|projection|Reads decision-backed valuation and FX-resolution contributions.
reconciliation|projection|Reads reconciliation readiness and transfer-match state for report disclosure.
""",
    ),
    units=units(
        """
@vo|base/types.py|PersonalReportingFrameworkId ReportLineId PolicyDimension
@vo|-|ReportLine BalanceSheetResponse IncomeStatementResponse FrameworkPolicyDecision FrameworkPolicyGap FrameworkPolicyMatrix PeriodSpan AnnualizedIncomeTotals NetWorthTimeSeriesPoint AccountLineageLine
@vo|base/cash_flow_types.py|CashFlowItem CashFlowResponse CashFlowSummary
@vo|base/data_quality_types.py|PersonalDataQualityHealthResponse QualityGrade InvariantStatus MonthContinuityBucket QualityActionItem
@vo|base/diagnostics.py|EquationDiagnosticCategory EquationDiagnosticResult
@svc|extension/diagnostics.py|diagnose_equation_imbalance run_balance_sheet_diagnostics
compute_personal_data_quality|svc|extension/data_quality_service.py
ReportSnapshot|agg
generate_balance_sheet|svc|extension/balance_sheet.py
generate_annualized_income_schedule|svc|extension/annualized_income.py
generate_income_statement|svc|extension/income_statement.py
generate_cash_flow|svc|extension/cash_flow.py
@svc|extension/_core.py|_aggregate_balances_sql _aggregate_net_income_sql
@svc|extension/net_worth.py|get_net_worth_timeseries get_net_worth_allocation_schedule get_category_breakdown get_account_trend
get_account_lineage|svc|extension/lineage.py
@vo|base/package_contribution.py|PackageSectionContribution PackageCashInputs
personal_report_package_target|fac|base/package_decision.py
personal_report_package_decision_ref|svc|extension/package_document.py
ReportingReadRepository|repo
@proj|-|ReportSnapshotProjection ReportTraceabilityProjection AccountLineageTreeProjection FrameworkPolicyDecisionProjection
"""
    ),
    interface="""
MAX_NET_WORTH_DAILY_POINTS PERSONAL_REPORT_PACKAGE_CONTRACT
PERSONAL_REPORT_PACKAGE_NOTES PackageAssembler PackageSectionContribution
personal_report_package_target personal_report_package_decision_ref
PackageDocumentVersionError EquationDiagnosticCategory EquationDiagnosticResult
diagnose_equation_imbalance run_balance_sheet_diagnostics current_package_readiness
report_coverage package_preview AnnualizedIncomeTotals CashFlowItem
CashFlowLineEventsPage CashFlowPreview CashFlowResponse CashFlowSummary
PersonalDataQualityHealthResponse QualityGrade InvariantStatus MonthContinuityBucket
QualityActionItem compute_personal_data_quality DEFAULT_INCLUDE_RESTRICTED
PACKAGE_INCLUDE_RESTRICTED PersonalReportingFrameworkId PolicyDimension ReportError
ReportLineId ReportSnapshot ReportType ReportingSnapshotService _add_months
_aggregate_balances_sql _aggregate_net_income_sql _combine_provenance _iter_periods
_month_end _month_start _normalize_currency _provenance_from_source_type
_quantize_money _quarter_start _signed_amount assemble_framework_balance_sheet
assemble_framework_income_statement
build_personal_report_package_traceability_payload
derive_user_framework_policy_result generate_balance_sheet
generate_annualized_income_schedule cash_flow_line_events cash_flow_period
cash_flow_preview generate_cash_flow generate_income_statement get_account_lineage
get_account_trend get_category_breakdown get_net_worth_allocation_schedule
get_net_worth_timeseries income_bucket is_valid_line_for_framework jsonable
package_currency package_dates package_snapshot_csv package_snapshot_document
package_snapshot_response package_snapshot_summary
register_manual_valuation_lines_provider render_balance_sheet_csv
render_cash_flow_csv render_income_statement_csv resolve_line_currency
""".split(),
    events=[],
    invariants=invs(
        """
@$t/test_reporting_package.py
interface-equals-published-language|The published language (contract.interface) equals __init__.__all__.|test_AC_reporting_1_1_only_all_is_the_published_language
reporting-cutover-inventory-declared|Reporting statement generators/core lanes are declared in units and mapped to the current implementation inventory.|test_AC_reporting_1_2_cutover_inventory_is_declared
manual-valuation-excluded-from-reporting-language|Manual_valuation stays out of reporting's published language.|test_AC_reporting_1_3_manual_valuation_is_not_published_reporting_surface
passes-own-governance-gate|Check_package_contract validates reporting with no violations.|test_AC_reporting_1_4_package_contract_gate_passes
@-
snapshot-orm-owner|ReportSnapshot and ReportType are reporting-owned ORM vocabulary and register exactly once on shared SQLAlchemy metadata.|$t/test_s3_pr_d_structure.py::test_AC_reporting_snapshot_ownership_and_metadata_registration
"""
    ),
    roadmap=acs(
        "reporting",
        """
@$be/reporting/test_reporting_calc_extraction.py|P1
single-owner.1|Manual-valuation line naming is defined only by pricing, its fact owner.|test_AC_reporting_single_owner_1_has_no_valuation_line_name_copy
dry-ssot.1|Pure reporting math is provided by `services.reporting_calc` and re-used by `services.reporting`.|test_reporting_calc_extraction|:exact
@$be/reporting/test_balance_sheet_opening_balance_gate.py|P1
opening-balance.1|A balance sheet with posted activity but no recorded opening balance emits an opening_balance_warnings entry.|test_AC2_16_4_balance_sheet_warns_when_opening_balance_missing
opening-balance.2|Once an opening-balance entry is posted for the account that triggered the degrade, the balance sheet's opening_balance_warnings clears to empty on the next generation.|test_AC2_16_4_balance_sheet_clears_warning_once_opening_balance_recorded
opening-balance.3|The net-worth allocation schedule surfaces the same opening_balance_warnings as the balance sheet.|test_AC2_16_4_net_worth_allocation_surfaces_opening_balance_warning
@$t/test_framework_reporting_epic_contract.py|P0|done|exact
framework.1|The framework registry SSOT and EPIC-020 define `personal_us_gaap_like` and `personal_hkfrs_like`, exclude a CN/CAS v1 framework.|test_AC20_1_1_framework_registry_defines_us_hk_personal_targets
lanes.1|The framework-reporting SSOT and EPIC-020 declare the six-lane fact-forward/target-backward architecture as mutually exclusive and collectively covering, with distinct lane owners.|test_AC20_2_1_mece_direction_matrix_declares_distinct_owner_lanes
target.1|The framework target package contract works backward from report outputs.|test_AC20_3_1_framework_target_contract_is_report_output_backward
policy.1|The v1 policy matrix covers cash and bank accounts, listed equities/ETFs, funds and money-market products, dividends and interest, brokerage fees, FX, RSU/ESOP/options.|test_AC20_4_1_policy_matrix_covers_personal_finance_domains
policy.2|The framework policy layer is read-only.|test_AC20_5_1_policy_layer_is_read_only_between_facts_and_report
ai.1|An AI measurement/disclosure suggestion affects trusted output only.|test_AC20_6_1_ai_suggestions_require_structured_reviewed_policy_fields
@$be/ai/test_streaming_contract.py|P0
export-envelope.1|ExportStreamEnvelope declares the wire media type and builds an attachment Content-Disposition header carrying the envelope's filename.|test_AC6_33_5_export_envelope_builds_attachment_headers
export-envelope.2|ExportStreamEnvelope rejects a media type outside the declared wire set at construction.|test_AC6_33_6_export_envelope_rejects_unknown_media_type
export-envelope.4|ExportStreamEnvelope rejects a filename carrying CR/LF, a double-quote, a semicolon, or a path separator, since the filename is interpolated into the Content-Disposition header and each of those characters would break out of it or inject a header.|test_AC6_33_9_export_envelope_rejects_unsafe_filename
@$be/reporting/test_reports_router.py|P0
export-envelope.3|GET /reports/export's response media type and Content-Disposition header equal what ExportStreamEnvelope would produce for the same filename.|test_AC6_33_8_export_response_matches_typed_envelope
balance-sheet.4|GET /reports/balance-sheet returns the generated balance sheet payload.|test_balance_sheet_endpoint
errors.4|The reports router endpoints respond successfully for an authenticated user.|test_income_statement_endpoint|P1
trust-signals.1|The balance sheet includes restricted holdings by default and exposes an include toggle.|test_AC5_16_1_balance_sheet_defaults_to_the_full_scope
trust-signals.2|Report responses preserve backend fx_warnings.|test_AC5_16_2_cash_flow_response_preserves_fx_warnings
csv-export.1|The backend CSV export supports cash-flow reports with date-range and currency filters.|test_AC5_17_1_cash_flow_export_returns_csv
@$be/reporting/test_reporting.py|P0
balance-sheet.1|The generated balance sheet satisfies the accounting equation.|test_balance_sheet_equation
income-statement.1|The income statement computes net income as income minus expenses.|test_income_statement_calculation
income-statement.3|The income statement rejects an invalid date range with a domain error.|test_income_statement_invalid_range|P1
cash-flow.1|The cash-flow statement is generated with operating, investing.|test_cash_flow_statement
cash-flow.2|A period with no cash movement generates an empty cash-flow statement, not an error.|test_cash_flow_empty_period|P1
kpis.2|Unrealized P&L is reflected in balance-sheet equity.|test_reporting_dashboard_fixture_exact_totals
lineage.2|Each cash-flow line carries its account anchor.|test_reporting_dashboard_fixture_exact_totals|P1
provenance.1|Report amount lines expose the normalized provenance enum.|test_AC22_13_1_report_amount_lines_expose_normalized_provenance|P1
@$be/reporting/test_reporting_fx.py|P0
balance-sheet.2|FX unrealized gain is calculated for foreign-currency balances on the balance sheet.|test_fx_unrealized_gain_calculation
balance-sheet.3|Multi-currency account balances aggregate into the base reporting currency on the balance sheet.|test_multi_currency_aggregation
income-statement.2|The income statement includes comprehensive income from FX effects.|test_income_statement_comprehensive_income|P1
fx.1|Report FX conversion falls back.|test_reporting_fx_fallbacks|P1
fx.2|Balance-sheet net income uses the FX fallback path.|test_balance_sheet_net_income_fx_fallback|P1
fx.3|Reports lazily resolve a missing cross rate from stored bridge rates.|test_reports_lazy_resolve_missing_hkd_sgd_from_bridge_rates
2728.1|Balance sheet lines expose each account source currency and native-currency balance alongside the report-currency amount.|test_AC_reporting_2728_1_balance_sheet_exposes_native_amount_when_fx_rate_missing|P1:exact
@$e2e/test_personal_financial_report_package.py|P0
balance-sheet.5|A historical as_of_date balance sheet excludes a portfolio position whose ManagedPosition.acquisition_date postdates that as_of_date.|test_personal_financial_report_package_post_merge_journey|P1:property
package-notes.3|The post-merge package proof asserts the notes endpoint, required note IDs.|test_personal_financial_report_package_post_merge_journey
package-traceability.3|The post-merge package proof fails trusted totals.|test_personal_financial_report_package_post_merge_journey
@$be/reporting/test_reporting_net_worth_components.py|P1
balance-sheet.6|A manual valuation component recorded only.|test_AC_reporting_balance_sheet_6_valuation_gap_disclosed_in_portfolio_warnings
net-worth-components.1|Retirement accounts, social-security personal balances, legacy CPF.|test_AC11_20_1_retirement_and_benefit_assets_are_restricted_assets_in_balance_sheet
net-worth-components.2|Net-worth allocation groups retirement and benefit balances under the retirement-and-benefit asset class.|test_AC11_20_2_net_worth_allocation_groups_retirement_and_benefit_assets
layer3.1|The income statement's classification coverage reads Layer 3 APPLIED TransactionClassification rows joined to their category accounts.|test_income_statement_includes_applied_classification_breakdown
layer3.3|Income statement payloads include the applied Layer 3 classification coverage breakdown.|test_income_statement_includes_applied_classification_breakdown
net-worth-components.3|Reports expose a net-worth allocation schedule grouped by asset class, liquidity class.|test_AC17_14_2_net_worth_allocation_groups_balance_sheet_sources
@$be/api/test_reports_router.py|P1
cash-flow.3|GET /reports/trend returns account trend data.|test_account_trend_with_period
cash-flow.4|GET /reports/breakdown returns the category breakdown.|test_category_breakdown_success
cash-flow.5|GET /reports/breakdown honors the requested period parameter.|test_category_breakdown_with_period
errors.3|Unauthenticated clients cannot access the reports endpoints.|test_unauthenticated_access
errors.5|GET /reports/{report_type}/snapshots returns the user's persisted report snapshots.|test_list_report_snapshots_returns_created_snapshots
layer3.2|ReportSnapshot rows are generated and queryable.|test_list_report_snapshots_returns_created_snapshots
@$be/reporting/test_cash_flow_preview_payload.py|P1|done|property
cash-flow.6|At one year of activity, GET /reports/cash-flow returns less than 100 KB with no more SQL statements than.|test_AC_reporting_cash_flow_6_year_scale_preview_is_bounded
cash-flow.7|Each GET /reports/cash-flow line is the sum and count of the document items of one activity, description and account.|test_AC_reporting_cash_flow_7_line_events_pages_equal_document|:exact
@$be/reporting/test_income_annualized_router.py|P1
kpis.1|The annualized income KPI endpoint groups the last 12 months of income.|test_annualized_income_endpoint_groups_last_12_month_income|P0
annualized-dashboard.1|GET /api/income/annualized returns {annualized_salary, annualized_bonus, annualized_dividend, annualized_total, currency, as_of} derived from the last 12 months of Income-type journal entries.|test_annualized_income_endpoint_groups_last_12_month_income
annualized-dashboard.2|GET /api/assets/restricted returns ESOP/RSU/locked holdings with {ticker, quantity, vesting_schedule, unlock_date, fair_value}.|test_restricted_assets_endpoint_returns_latest_locked_holdings
annualized-dashboard.3|GET /api/income/annualized converts mixed-currency annualized income totals into the dashboard reporting currency.|test_AC11_8_7_annualized_income_endpoint_converts_mixed_currency_totals
@$be/reporting/test_reporting_extreme_fallbacks.py|P1
kpis.4|Account trend raises when a prefetched non-base FX rate is missing.|test_account_trend_raises_when_prefetched_rate_missing
kpis.5|Category breakdown raises.|test_category_breakdown_raises_when_prefetched_rate_missing
kpis.6|Cash flow raises when the start-date non-base FX rate is missing.|test_cash_flow_raises_when_start_date_rate_missing
kpis.7|Cash flow raises when the end-date FX rate is missing, propagating FxRateError.|test_cash_flow_raises_when_end_date_rate_missing
@$be/api/test_personal_report_package_contract.py|P0
package-contract.1|The document-embedded package contract defines the required section IDs, labels, owners.|test_AC5_9_1_package_contract_defines_required_sections
package-contract.2|The package contract exposes Decimal-safe total fields and explicit period/as-of semantics.|test_AC5_9_2_package_contract_marks_decimal_totals_and_period_semantics
package-annualized.1|The package contract requires the typed annualized_income_long_term section inside PersonalReportPackageDocument.|test_AC5_11_1_package_contract_marks_annualized_schedule_ready
package-notes.1|The package notes endpoint returns the required note IDs, owner EPICs, source states.|test_AC5_12_1_package_notes_endpoint_returns_required_note_taxonomy
package-notes.2|The package contract marks notes ready and points at the notes endpoint.|test_AC5_12_2_package_contract_marks_notes_ready
package-traceability.1|The package traceability endpoint returns source-to-ledger anchors per report line.|test_AC5_13_1_package_traceability_endpoint_returns_section_line_anchors
package-traceability.2|The traceability appendix exposes explicit completeness states where anchors are unavailable.|test_AC5_13_2_package_traceability_declares_completeness_warnings
package-traceability.4|The package traceability endpoint returns current-user dynamic source identifiers and excludes unrelated-user anchors.|test_AC5_13_5_package_traceability_returns_dynamic_current_user_identifiers
trust-signals.3|Package traceability lines expose source classes, proof level, anchor count.|test_AC5_13_1_package_traceability_endpoint_returns_section_line_anchors
package-snapshot.1|POST /api/reports/package/generate creates an immutable package snapshot.|test_AC5_19_1_package_generate_creates_draft_or_trusted_snapshot
package-snapshot.2|Package snapshot list/reopen endpoints are user-scoped and reopening returns the original payload.|test_AC5_19_2_package_snapshot_get_is_user_scoped_and_immutable
package-snapshot.3|Package JSON and CSV downloads are derived from a saved snapshot.|test_AC_reporting_package_document_4_exports_the_selected_frozen_document
package-document.4|A selected frozen document is the only JSON/CSV export input.|test_AC_reporting_package_document_4_exports_the_selected_frozen_document|:property
package-document.5|Package decision emission and frozen snapshot persistence share the caller-owned transaction.|test_AC_reporting_package_document_5_trace_and_snapshot_rollback_together|:exact
source-anchors.1|Package traceability resolves journal source IDs to typed source anchors and blocks unknown source IDs.|test_AC19_10_1_unknown_journal_source_ids_are_not_reported_as_statement_transactions
@$be/reporting/test_financial_logic_audit.py|P0
logic-audit.1|Cash-flow beginning cash, ending cash.|test_AC5_10_1_cash_flow_uses_cumulative_cash_balances
logic-audit.2|Cash-flow operating, investing.|test_AC5_10_2_cash_flow_activity_totals_preserve_signs
package-document.8|The PackageDocument cash-flow section receives an exact typed set of cash-balance account identities from authoritative bank-statement contributions.|test_AC_reporting_package_document_8_uses_exact_cash_inputs_not_account_names|:exact
@$be/reporting/test_annualized_income_schedule.py|P0
package-annualized.2|The annualized income package schedule converts mixed-currency income and restricted totals into one reporting currency.|test_AC5_11_3_AC11_11_3_annualized_schedule_converts_mixed_currency_totals
package-annualized.3|The reporting-owned annualized section returns annualized salary, bonus, dividend, total income, currency, as-of date.|test_AC11_11_1_AC11_11_2_annualized_schedule_includes_income_and_restricted_treatment
package-annualized.4|The schedule includes ESOP/RSU/stock-option restricted holdings with valuation basis, vesting/unlock metadata, fair value.|test_AC11_11_1_AC11_11_2_annualized_schedule_includes_income_and_restricted_treatment
package-annualized.5|Each restricted holding's valuation_basis surfaces the snapshot's structured evidence basis enum value.|test_AC11_11_4_annualized_schedule_surfaces_structured_valuation_basis
@$be/reporting/test_report_traceability_linear.py|P1|done|exact
package-traceability.5|The traceability appendix builder returns the pre-#2583 output for a fixed contribution set.|test_AC_reporting_package_traceability_5_output_equals_pre_change_golden
package-traceability.6|The traceability appendix builder is linear in the number of contributions.|test_AC_reporting_package_traceability_6_builder_is_linear_in_contributions|:property
@$be/reporting/test_package_preview_payload.py|P1|done|property
package-traceability.7|At one year of anchored activity, GET /reports/package returns less than 300 KB with no more SQL statements than.|test_AC_reporting_package_traceability_7_year_scale_preview_is_bounded
package-traceability.8|GET /reports/package/line-details returns, page by page, the same details for each line anchor as a frozen snapshot of the same data, in the same order.|test_AC_reporting_package_traceability_8_evidence_pages_equal_snapshot|:exact
@$be/reporting/test_package_preview_policy_and_cash_flow.py|P1|done|exact
package-traceability.9|At one year of categorized statement activity, GET /reports/package returns less than 300 KB with no more SQL statements than.|test_AC_reporting_package_traceability_9_year_scale_preview_with_categories_is_bounded|:property
package-traceability.10|GET /reports/package/policy-decisions returns, page by page, the framework policy decisions of a frozen snapshot of the same data, in the same order.|test_AC_reporting_package_traceability_10_policy_decision_pages_equal_snapshot
package-traceability.11|GET /reports/package/cash-flow-events returns, page by page, every lineage record of the frozen cash flow of the same data on exactly one line, for the cash accounts of the authoritative bank statements.|test_AC_reporting_package_traceability_11_cash_flow_event_pages_equal_snapshot
@$be/reporting/test_package_document.py|P0|done|exact
package-document.1|The personal report package is a versioned, Decimal-safe document with required typed balance-sheet, income-statement, cash-flow, investment, annualized-income, notes, traceability.|test_AC_reporting_package_document_1_requires_typed_delivery_sections
package-document.2|Preview, generation, persistence, reopen.|test_AC_reporting_package_document_2_has_one_assembler_and_no_live_package_export
package-document.3|Trusted/final package state is the projection of one persisted CODE-ONLY TraceRecord MANIFEST decision over the exact current contributing decisions and deterministic section observation.|test_AC_reporting_package_document_3_trust_is_one_trace_decision_fold
package-document.6|A whole-production-tree certificate permits one PackageDocument producer, forbids consumer-owned readiness/trust calculations and live selected-snapshot reads.|test_AC_reporting_package_document_6_producer_and_consumer_closure
package-document.7|PackageAssembler adapts extraction, ledger.|test_AC_reporting_package_document_7_manifest_folds_only_typed_contributions
package-document.9|Every authoritative PackageSectionContribution carries one typed audit decision reference containing its exact target and assertion.|test_AC_reporting_package_document_9_requires_exact_decision_coordinates
package-document.10|Reporting publishes one pure package-decision coordinate builder over the exact frozen document semantics.|test_AC_reporting_package_document_10_reconstructs_exact_decision_coordinates
package-document.13|Package assembly builds the traceability appendix and notes once per assembly and reuses the balance-sheet ending unrealized FX gain/loss for the income statement.|test_AC_reporting_package_document_13_single_pass_traceability_and_unrealized_fx_reuse
2466.1|Every cash-flow proof reason code emitted by generate_cash_flow maps to its own distinct cause and action message in cash_flow_proof_reason_text and package blocker rendering.|test_AC_reporting_2466_1_every_cash_flow_proof_reason_has_its_own_text|P1
2623.1|Framework_policy_facts_for_user includes all active user accounts including system accounts.|test_AC_reporting_2623_1_system_accounts_receive_l1_policy_mappings|P1
2667.1|Personal_report_package_decision_ref omits unset excluded_holdings on pre-2655 frozen package documents.|test_AC_reporting_2667_1_pre_2655_frozen_package_keeps_decision_ref_and_locks_bound_defaults|P1
@$fe/__tests__/personalReportPackagePage.test.tsx|P1
package-document.12|The Full package tab takes its period from the dimension bar.|AC-reporting.package-document.12 previews and generates the selected month through the page|P0:exact
net-worth-scope.15|The Package tab balance sheet card takes its net worth label from the recorded scope.|#2645 labels the package net worth from the recorded scope and names each excluded class
net-worth-scope.17|A package snapshot frozen.|#2645 shows no bare net worth for a snapshot frozen before the scope record|P0
net-worth-scope.23|The Package tab passes context.include_restricted of the shown document to the balance sheet card.|#2645 labels the package net worth from the scope that the document context records
fe-viz-reports.1|The annualized income figures show in the Full package tab from the package document.|AC5.11.2 renders annualized income schedule values and restricted treatment|P0
fe-viz-reports.3|Frontend personal package page renders the contract section IDs and labels from the API contract.|AC5.9.3 renders personal package contract sections from API|P0
fe-viz-reports.4|Frontend/export contract surfaces stable export format and CSV columns for package consumers.|AC5.9.4 renders export contract metadata
fe-viz-reports.5|Frontend personal package page renders annualized income totals and restricted treatment from the schedule endpoint.|AC5.11.2 renders annualized income schedule values and restricted treatment|P0
fe-viz-reports.6|Frontend personal package page renders notes and disclosure basis from the notes endpoint.|AC5.12.3 renders package notes and disclosure basis|P0
fe-viz-reports.7|Frontend personal package page renders source, ledger, review.|AC5.13.3 AC5.16.3 AC5.16.4 renders traceability appendix source, ledger, review, and identifiers|P0
fe-viz-reports.10|Personal report package traceability renders concrete source and ledger identifiers.|AC5.13.3 AC5.16.3 AC5.16.4 renders traceability appendix source, ledger, review, and identifiers|P0
fe-viz-reports.11|Personal report package page exposes an authenticated CSV export action.|AC5.17.2 downloads package CSV through authenticated apiDownload|P0
fe-viz-reports.12|The package page shows recent snapshots, can generate a new snapshot.|AC5.19.4 generates and downloads package snapshots|P0
fe-ia-reports.14|The report package titles its sections with human-readable labels.|AC22.8.1 titles package sections with human labels, not developer snake_case identifiers
fe-ia-reports.15|The loaded report package starts with a readable cover sheet and table of contents that expose the package id, selected framework, report date.|AC22.8.2 AC22.13.3 renders a readable package cover and linked table of contents
fe-ia-reports.16|The unselected-framework and framework-package loading states reserve the package layout with guidance or skeleton placeholders, never a blank text-only pre-selection or loading screen.|AC20.6.1 AC22.8.3 AC22.13.3 requires explicit framework selection before loading framework-scoped package output
fe-ia-reports.23|The loaded report package uses reader-facing labels for evidence coverage, reporting basis.|AC22.19.1 renders the loaded package with reader-first labels before proof internals
fe-ia-reports.24|Explicit `Audit details` disclosures keep the same source-trust, framework-policy, traceability, blocker, matrix-version, line-id, confidence, review-state.|AC22.19.2 keeps proof and policy internals in keyboard-reachable audit details
fe-ia-reports.25|Print/save and export metadata default to the reader-first hierarchy.|AC22.19.3 keeps export proof metadata behind a print-hidden export audit disclosure
fe-remainder-reports.1|The report package traceability surface exposes a lineage panel from at least one report traceability row.|AC18.9.4 AC18.9.5 AC18.9.6 opens an Evidence Graph lineage panel from report traceability|P2
fe-remainder-reports.2|The lineage panel renders source document, extracted record, atomic fact, ledger entry, ledger line.|AC18.9.4 AC18.9.5 AC18.9.6 opens an Evidence Graph lineage panel from report traceability|P2
fe-remainder-reports.3|Tests cover report line to source document navigation and source document to impacted ledger/report navigation.|AC18.9.4 AC18.9.5 AC18.9.6 opens an Evidence Graph lineage panel from report traceability|P2
fe-remainder-reports.11|Personal report package page renders readiness state and blocker links.|AC19.5.4 renders package readiness before report package output
fe-remainder-reports.12|Personal report package page renders non-blocked readiness states.|AC19.5.5 renders non-blocked readiness states without blocker cards
fe-remainder-reports.14|Personal report package page renders decision authority coverage.|AC19.9.2 renders decision authority coverage before traceability details|P0
fe-fetch-budget.5|The Overview and Full package tabs of `/reports` share one cached package preview.|AC-reporting.fe-fetch-budget.5 the Reports hub and the package page share one preview request
fe-fetch-budget.7|The package page requests the details of a traceability line only.|AC-reporting.fe-fetch-budget.7 loads the details of a traceability line only after the user opens the line
fe-fetch-budget.9|The package page requests the framework policy decisions only.|AC-reporting.fe-fetch-budget.9 loads the policy decisions only after the user opens the audit details
@$be/reporting/test_year_scale_reporting.py|P1
year-scale.1|At a full year's transaction volume the three statements tie out and generate within a wall-clock backstop, guarding against a silent O regression.|test_AC5_20_year_scale_reporting_ties_out_within_budget
net-worth-timeseries.4|At a year of activity, GET /reports/net-worth/timeseries for 6 months of daily points makes fewer than 30 SQL statements and answers in less than 500 ms.|test_AC_reporting_net_worth_timeseries_4_six_month_daily_series_within_budget
@$be/reporting/test_income_typed_currency.py|P2
income-typed.1|AnnualizedIncomeResponse.currency is the shared typed CurrencyCode, not a soft str.|test_AC5_32_1_currency_code_type_validates_and_normalizes
income-typed.2|Income totals accumulate in a typed AnnualizedIncomeTotals Decimal intermediate, not a string-keyed dict.|test_AC5_32_2_annualized_income_totals_is_typed_intermediate
income-typed.3|Resolve_line_currency centralizes the line/account/base currency fallback + normalization.|test_AC5_32_3_resolve_line_currency_uses_canonical_fallback_chain
income-typed.4|An explicit FX-failure response model is declared for the income endpoint.|test_AC5_32_4_fx_conversion_error_response_model_declared
income-typed.5|Currency normalization is a single shared helper, not duplicated strip/upper.|test_AC5_32_5_normalize_currency_code_is_shared_helper
income-typed.6|The income endpoint normalizes a soft base-currency setting in its response.|test_AC5_32_6_endpoint_returns_normalized_currency_for_soft_base_config
@$be/api/test_typed_contract_sweep.py|P2
snapshots-typed.1|GET /reports/{report_type}/snapshots rejects an unknown report_type with 422.|test_AC5_36_1_report_snapshots_unknown_type_returns_422
snapshots-typed.2|A valid report_type returns a typed list[ReportSnapshotSummary] response.|test_AC5_36_2_report_snapshots_valid_type_returns_typed_list
@$be/reporting/test_reporting_shift_left.py|P0
journeys.1|The core-journey E2E views the balance sheet end to end.|test_balance_sheet_accounting_equation_articulation
journeys.2|The core-journey E2E views the income statement end to end.|test_income_statement_revenues_expenses_net_income
journeys.3|The core-journey E2E views the cash-flow report end to end.|test_cash_flow_bridge_reconciliation
journeys.4|The core-journey E2E navigates every reports endpoint.|test_multi_period_reporting_and_cta_adjustment|P1
@$be/reporting/test_net_worth_timeseries.py|P1
net-worth-timeseries.1|GET /api/reports/net-worth/timeseries?from=YYYY-MM-DD&to=YYYY-MM-DD&granularity=monthly/daily returns [{date, total_assets, total_liabilities, net_worth}].|test_net_worth_timeseries_router
net-worth-timeseries.2|Net worth time-series respects multi-currency.|test_net_worth_timeseries_uses_historical_fx_per_point
net-worth-timeseries.5|A monthly net worth time-series holds at most 366 points and keeps the latest months.|test_AC_reporting_net_worth_timeseries_5_monthly_series_starts_at_first_month_with_value
@$be/reporting/test_net_worth_one_definition.py|P0
net-worth-scope.1|The balance sheet net worth, the balance sheet equity side total, the last point of the net worth series and the allocation net worth are equal.|test_AC_reporting_net_worth_scope_1_every_surface_reads_one_net_worth
net-worth-scope.2|A manual valuation goes to net_worth_adjustment_gain_loss, never to unrealized FX or CTA.|test_AC_reporting_net_worth_scope_2_manual_valuations_stay_out_of_fx_and_cta
net-worth-scope.3|With restricted holdings excluded, the balance sheet and the allocation return excluded_holdings.|test_AC_reporting_net_worth_scope_3_balance_sheet_names_each_excluded_class_and_amount
net-worth-scope.8|Each net worth allocation source line carries source_type, source_id, label and value.|test_AC_reporting_net_worth_scope_8_allocation_sources_carry_no_link|P1
net-worth-scope.9|With restricted holdings excluded, an excluded valuation with no FX rate to the report currency does not fail the report.|test_AC_reporting_net_worth_scope_9_excluded_valuation_without_fx_rate_does_not_fail_the_report
net-worth-scope.10|An included valuation with no FX rate to the report currency still fails the balance sheet with the FX ReportError.|test_AC_reporting_net_worth_scope_10_included_valuation_without_fx_rate_still_fails_the_report
net-worth-scope.11|The personal report package carries excluded_holdings in its balance sheet.|test_AC_reporting_net_worth_scope_11_package_discloses_each_excluded_class
net-worth-scope.12|A package generate body without include_restricted reads PACKAGE_INCLUDE_RESTRICTED in the route.|test_AC_reporting_net_worth_scope_12_generate_without_scope_reads_the_package_default|P1
net-worth-scope.13|GET /reports/data-quality answers 200.|test_AC_reporting_net_worth_scope_13_data_quality_stays_available_without_a_valuation_fx_rate|P1
net-worth-scope.14|A restricted holding without an FX rate does not fail the package.|test_AC_reporting_net_worth_scope_14_package_lists_a_restricted_holding_without_fx_rate|P1
net-worth-scope.18|Data quality runs the equation check with include_restricted=False and reports that result, also.|test_AC_reporting_net_worth_scope_18_data_quality_reads_the_liquid_check_after_an_fx_error|P1
net-worth-scope.19|Data quality falls back only for an FX error of the full scope.|test_AC_reporting_net_worth_scope_19_data_quality_raises_other_errors|P1
net-worth-scope.20|The package document context records include_restricted.|test_AC_reporting_net_worth_scope_20_package_records_its_scope
net-worth-scope.22|A package document frozen in the shape of main 685533f0f reloads to the same JSON.|test_AC_reporting_net_worth_scope_22_main_shape_document_keeps_its_decision_version
@$fe/__tests__/uiGapAudit.netWorthTimeSeries.test.tsx|P2
net-worth-scope.4|The net worth chart requests its series with the include_restricted scope of the dimension bar and caches each scope apart.|#2645 requests the series in the restricted-holdings scope of the dimension bar|P1
fe-viz-reports.28|The net worth chart of the Balance sheet tab renders an ECharts line chart with a date X-axis and a net-worth Y-axis.|AC5.7.2/AC5.7.6 mounts an ECharts-backed net worth line chart
fe-viz-reports.29|The net worth chart reads the period of the dimension bar, with one point per day up to 92 days and one point per month for a longer period.|AC5.7.4 reads the period of the dimension bar and draws months for a period longer than one quarter
fe-viz-reports.30|Empty-state placeholder rendered when fewer than 2 data points exist.|AC5.7.5 renders an empty state when fewer than two points exist
fe-viz-reports.31|A frontend unit test mounts the net worth chart and asserts that the chart container exists.|AC5.7.2/AC5.7.6 mounts an ECharts-backed net worth line chart
fe-viz-reports.34|The net worth chart caches each period under a query key of from, to, granularity and currency.|caches each period so a revisit within the stale time sends no request|P1
@$fe/__tests__/dashboardPage.test.tsx|P1
net-worth-scope.5|Home labels a net worth without restricted holdings as Liquid net worth and lists each excluded asset class with its amount.|AC11.8.5 defaults to the full net worth and labels each excluded class when restricted holdings are excluded
fe-report-surfaces.1|Home shows a loading line in each statement card until its own statement resolves.|AC16.12.1 shows loading state before dashboard data resolves|P2
fe-report-surfaces.2|Home shows a failed statement with a retry action that refetches it.|AC16.12.2 renders error fallback and retry action on failure|P2
fe-report-surfaces.3|Home renders the dimension bar and the three statement cards with the live metrics of the period.|AC16.12.3 AC22.1.2 renders the dimension bar and the three statement cards of the period|P2
fe-report-surfaces.4|Home shows zero metrics and no line list for a period without data.|AC16.12.4 shows zero metrics and no line list for an empty period|P2
fe-report-surfaces.5|Home asks a user without a source to upload the first statement in its one action banner.|AC22.16.1 AC16.12.17 AC16.12.18 asks a new user to upload the first statement|P2
fe-report-surfaces.6|The Home upload action links to the `/upload` page in one click.|AC22.16.1 AC16.12.17 AC16.12.18 asks a new user to upload the first statement|P2
fe-report-surfaces.7|Home shows no action banner.|AC16.12.19 hides the action banner when nothing needs attention|P2
fe-ia-reports.1|The authenticated Home renders the dimension bar, the three statement cards with key numbers.|AC16.12.3 AC22.1.2 renders the dimension bar and the three statement cards of the period
fe-ia-reports.7|Home is lean: one three-statement cockpit, no analytics panel and no second block that repeats its metrics.|AC22.4.4 keeps Home lean: one cockpit and no analytics panel or duplicate metric block
fe-ia-reports.9|Home surfaces at most one primary next action.|AC22.16.2 AC22.5.6 routes the confirmation count to the one /audit queue
fe-ia-reports.20|The Home upload action targets `/upload`.|AC22.16.1 AC16.12.17 AC16.12.18 asks a new user to upload the first statement
fe-ia-reports.21|Home presents one confidence-ranked attention entry point.|AC22.16.2 AC22.5.6 routes the confirmation count to the one /audit queue
fe-viz-reports.27|Home keeps the statement cards when the advisor suggestions fail.|renders the advisor brief after the statement cards and keeps the cockpit when suggestions fail
fe-remainder-reports.4|Home shows the workflow next action only as one action banner.|AC19.4.3 shows one action banner that follows the workflow next action|P0
fe-remainder-reports.5|The Home action banner renders.|AC19.4.2 AC16.16.1 renders the action banner before the dimension bar and the statement cards|P0
fe-remainder-reports.6|The Home action banner follows the `href` and the label of `workflow.status.next_action`.|AC19.4.3 shows one action banner that follows the workflow next action|P0
fe-remainder-reports.9|A failed workflow status does not hide the Home statement cards and shows no error on Home.|AC19.4.6 keeps the statement cards visible when the workflow status fails|P0
@$fe/__tests__/balanceSheetPage.test.tsx|P1
net-worth-scope.6|The Balance sheet tab shows manual and market valuations on their own equity line.|#2645 shows manual valuations on their own equity line, never in the FX and CTA line
net-worth-scope.7|The Balance sheet tab lists each asset class that the scope.|#2645 names each class and amount that the scope without restricted holdings excludes
api-vectors.2|The frontend balance-sheet page test consumes the committed reporting conformance vector verbatim as its mock data.|AC16.14.2 / test_AC8_13_48 renders string totals and refetches by date
fe-report-surfaces.10|The Balance sheet tab renders loading and error retry states.|AC16.14.1 renders loading and error retry states|P2
fe-report-surfaces.11|The Balance sheet tab renders totals and account sections on successful fetch.|AC16.14.2 / test_AC8_13_48 renders string totals and refetches by date|P2
fe-report-surfaces.12|The Balance sheet tab toggles account tree expansion controls.|AC16.14.3 toggles tree expansion controls|P2
fe-viz-reports.8|Balance sheet page exposes the restricted-holdings include toggle and renders equation component detail.|AC16.14.2 / test_AC8_13_48 renders string totals and refetches by date|P0
fe-viz-reports.9|Balance sheet, income statement.|AC16.14.2 / test_AC8_13_48 renders string totals and refetches by date|P0
2728.2|Balance sheet and StatementCockpit display the Processing clearing account as Transfers in transit with a glossary hint.|AC-reporting.2728.2 labels Processing as Transfers in transit and discloses foreign-currency native balances
2728.3|Clicking either the account name or the dotted-underlined amount on a Balance Sheet or Income Statement line opens AccountLineageDrawer.|AC-reporting.2728.3 opens the source drill-down from either the account name or the dotted-underlined amount
2654.2|On Home and on the Balance sheet tab, a manual valuation line links to /portfolio?panel=evidence and never requests GET /reports/account-lineage with a non-account id.|AC-reporting.2654.2 routes manual valuation lines to /portfolio?panel=evidence without calling account-lineage
@$e2e/test_brokerage_upload_to_portfolio_value.py|P0
portfolio-valuation-gate.1|The brokerage portfolio gate validates market valuation adjustment lines even.|test_portfolio_valuation_gate_ignores_unrelated_negative_asset_lines
portfolio-valuation-gate.2|Brokerage portfolio gate failures include holdings, valuation adjustment, non-portfolio asset.|test_portfolio_valuation_gate_failure_diagnostics_are_actionable
@$fe/__tests__/reportsCockpit.test.tsx|P1
fe-report-surfaces.8|`/reports` renders the tabs Overview, Balance sheet, Income statement, Cash flow and Full package.|AC-reporting.fe-period-cockpit.3 renders the five report tabs, selects the tab of the URL, and keeps the dimensions in each tab link|P2
fe-report-surfaces.9|The Balance sheet tab states the accounting equation Assets = Liabilities + Equity and its balance status.|AC16.12.12 states the accounting equation on the Balance sheet tab|P2
fe-ia-reports.2|The `/reports` Overview shows the three statement cards with the live figures of the period.|AC22.3.1 leads with the three statement cards and their live figures for the period
fe-ia-reports.3|Cash Flow and the Personal Report Package are tabs of `/reports` next to the Balance sheet and Income statement tabs.|AC-reporting.fe-period-cockpit.3 renders the five report tabs, selects the tab of the URL, and keeps the dimensions in each tab link
fe-ia-reports.18|The `/reports` Overview has no reconciliation block and no link into the Advanced `/reconciliation` surface.|AC22.9.1 keeps every Overview link inside the everyday surfaces, not the Advanced reconciliation surface
fe-viz-reports.32|The Reports cockpit renders package readiness state, blocker count, next action.|AC5.37.1 renders trust-first readiness before report cards
fe-viz-reports.33|The Reports cockpit shows a contained unavailable state.|AC5.37.2 preserves report navigation when readiness is unavailable|-|non-goals-not-budgeting-app
fe-period-cockpit.3|`/reports` shows the three statements and the report package as tabs of one page.|AC-reporting.fe-period-cockpit.3 renders the five report tabs, selects the tab of the URL, and keeps the dimensions in each tab link
@$fe/__tests__/incomeStatementPage.test.tsx|P2
fe-report-surfaces.13|The Income statement tab renders loading and error retry states.|AC16.14.4 renders loading and error retry states
fe-report-surfaces.14|The Income statement tab renders KPI cards and category lists on success.|AC16.14.5 / test_AC8_13_48 renders string KPI cards and category lists
fe-report-surfaces.15|The Income statement tab tag filters can be selected, removed one by one and cleared.|AC16.14.6 supports selecting and clearing tags
@$fe/__tests__/cashFlowPage.test.tsx|P2
fe-report-surfaces.16|The Cash flow tab renders loading and error retry states.|AC16.14.7 renders loading and error retry states
fe-report-surfaces.17|The Cash flow tab renders summary and section cards on success.|AC16.14.8 / test_AC8_13_48 renders string summary and activity sections
fe-report-surfaces.18|The Cash flow tab renders the sankey chart when a summary exists.|AC16.14.9 renders sankey chart when summary exists
fe-ia-reports.10|Clicking a cash-flow amount opens the account-lineage drawer for that account's contributing journal lines.|AC22.7.1 drills a cash-flow amount down to its account lineage|P1
fe-ia-reports.12|The Cash Flow statement renders a reconciliation that ties beginning cash + net cash flow to ending cash.|AC22.7.3 flags cash that does not tie (beginning + net != ending)|P1
fe-fetch-budget.8|The Cash flow tab requests the events of a statement line only.|AC-reporting.fe-fetch-budget.8 loads the events of a cash-flow line only after the user expands the line|P1
@$fe/__tests__/chartsComponents.test.tsx|P2
fe-report-surfaces.19|Bar and pie chart components render semantic labels and filtered data.|AC16.19.10 bar chart and pie chart render labels and filtered segments
2548.3|BarChart and PieChart render formatted value labels, percentage shares.|AC-reporting.2548.3 renders axis scale bounds, formatted values, and percentage shares across chart components|P1
@$fe/__tests__/sankeyChartComponent.test.tsx|P2
fe-report-surfaces.21|Sankey chart builds empty-state and data-state options for inflow and outflow links.|AC16.21.7 renders empty-state option when no series data is provided
fe-report-surfaces.22|Sankey chart recomputes theme-aware colors.|AC16.21.8 recomputes theme-driven colors on root attribute change
@$fe/__tests__/balanceSheetDrilldown.test.tsx|P1
fe-ia-reports.4|A reusable lineage drill-down component lets a user click any amount on the Balance Sheet or Income Statement, list the contributing journal lines.|AC22.3.4 lists contributing journal lines and opens the lineage chain for one
fe-ia-reports.5|Accounts/amounts with no contributing lines or no graph-compatible anchor degrade gracefully with an explicit empty/"no source linked" state and no crash.|AC22.3.5 shows an empty state when no transactions contribute
@$fe/__tests__/reportPageShell.test.tsx|P1
fe-viz-reports.13|`ReportPageShell` renders title, description.|AC5.33.1 renders title, description, toolbar, and body content
fe-viz-reports.14|`ReportPageShell` renders the loading skeleton while `isLoading`.|AC5.33.2 shows loading skeleton while loading
fe-viz-reports.15|`ReportPageShell` renders the error message with a working Retry action on `isError`.|AC5.33.3 shows error message and retries on click
@$fe/__tests__/reportToolbar.test.tsx|P1
fe-viz-reports.16|`ReportToolbar` composes the AI-prompt action and the CSV export action from its props.|AC5.33.4 renders the AI prompt and the caller-provided export control, without a Home link
fe-viz-reports.17|`AiPromptAction` links to the chat route with a URL-encoded prompt.|AC5.33.5 links to chat with url-encoded prompt
@apps/frontend/playwright/report-readiness.spec.ts|P1
fe-ia-reports.17|Desktop and mobile Playwright smoke covers report-package framework selection, cover, table of contents, readiness.|${scenario.name} renders cover, contents, and readiness before package output
fe-remainder-reports.13|Report readiness has route-level Playwright smoke coverage.|${scenario.name} renders cover, contents, and readiness before package output
@$fe/__tests__/reportFilters.test.tsx|P1
fe-viz-reports.18|The dimension bar sets the period preset and steps to the previous or next period.|AC-reporting.fe-period-cockpit.2 sets the preset and steps the period through the URL
fe-viz-reports.19|The dimension bar shows the base currency until the URL names one.|AC5.34.2 shows the base currency until the URL names one and writes the selected currency to the URL
@$fe/__tests__/useReportFilters.test.ts|P1
fe-viz-reports.20|`useReportFilters` reads the tab, period, end, currency and scope from the URL and falls back to the defaults on invalid values.|AC-reporting.fe-period-cockpit.2 reads the dimensions from the URL and falls back to defaults on invalid values
fe-viz-reports.21|`reportsHref` builds `/reports` tab links that keep the dimension query.|AC-reporting.fe-period-cockpit.2 builds tab links that keep the dimension query
fe-viz-reports.22|`useReportFilters` writes each dimension change to the URL and omits default values.|AC-reporting.fe-period-cockpit.2 writes each dimension change to the URL and omits default values
fe-viz-reports.23|The redirects of the old report routes keep their query.|AC-reporting.fe-period-cockpit.2 reads the dimensions from the URL and falls back to defaults on invalid values
fe-period-cockpit.1|The period presets 1M, 1Q, 1Y, YTD, 3Y and All resolve to their first and last day.|AC-reporting.fe-period-cockpit.1 moves a period back and forward by one period length and stops at today
fe-period-cockpit.2|The period, the period end, the currency and the restricted-holdings scope live only in the URL.|AC-reporting.fe-period-cockpit.2 writes each dimension change to the URL and omits default values
fe-period-cockpit.7|The default view and the `All` preset start no earlier than `coverage_start` of `GET /reports/coverage` for their period end.|AC-reporting.fe-period-cockpit.7 starts only the default view and All no earlier than the coverage start
@$fe/__tests__/useStatementCockpit.test.ts|P1
fe-viz-reports.24|`useStatementCockpit` reads the balance sheet at the period end and at the opening date.|AC5.35.1 reads the four statement sources of the dimension-bar period
fe-viz-reports.25|`useStatementCockpit` turns a missing statement list, total or currency into an empty list, a zero decimal string or the fallback currency.|AC5.35.2 normalizes missing statement fields to empty lists, zero decimal strings and typed warnings
fe-viz-reports.26|`useStatementCockpit` surfaces the first error and a retry that refetches only the failed source.|AC5.35.3 surfaces the first error and a retry that refetches only the failed source
@$fe/__tests__/homeStatements.test.tsx|P1
fe-ia-reports.26|Each Home statement card links to its `/reports` tab and keeps the dimension query.|deep-links each of the three statements to its report tab and keeps the period
fe-period-cockpit.4|Home and the `/reports` Overview show one three-statement cockpit.|AC-reporting.fe-period-cockpit.4 shows the live metrics of the period on each statement card
fe-period-cockpit.5|A segmented control selects one statement.|AC-reporting.fe-period-cockpit.5 switches the statement with the segmented control and drills a row into its source transactions
@$be/reporting/test_report_integrity.py|P0|done|exact
report-integrity.1|Processing identity retains visible in-transit assets.|test_processing_survives_framework_reporting
report-integrity.2|Authoritative account opening stock effective at the report start enters beginning cash.|test_opening_stock_is_beginning_cash
report-integrity.3|First stock observed after the selected period start is separately disclosed as a stock adjustment with an explicit coverage blocker.|test_midperiod_opening_is_explicit_incomplete_coverage
report-integrity.4|Framework income lines preserve authorized posted economic categories and exactly reconcile mixed-category account amounts in both personal frameworks.|test_posted_categories_survive_framework_mapping
report-integrity.5|Missing or unsupported posted categories stay explicitly other income or expense.|test_uncategorized_history_is_not_investment_activity
report-integrity.6|Archiving accounts never removes their posted historical amounts, cash identities, valuation basis or FX revaluation from period reports.|test_archiving_preserves_historical_reports
report-integrity.7|Persisted source-backed ledger facts remain correctly classified and usable.|test_persisted_package_integrity
@$be/reporting/test_cash_event_projection.py|P0|done|exact
cash-events.1|Only journal entries touching an exact cash identity can produce cash-flow activity.|test_AC_reporting_cash_events_1_only_cash_touch_events_are_classified
cash-events.2|Cash events are classified only from unambiguous full-event evidence with authoritative producer provenance.|test_AC_reporting_cash_events_2_event_classification_is_authoritative
cash-events.3|Direct and Processing-mediated internal transfers among cash and cash-equivalent identities emit no operating, investing, or financing activity.|test_AC_reporting_cash_events_3_internal_transfers_are_neutral
cash-events.4|The cash bridge separately discloses classified activity, unclassified cash.|test_AC_reporting_cash_events_4_cash_bridge_ties_exactly
cash-events.5|Every cash-event query predicates both JournalEntry.user_id and Account.user_id and rejects an entry containing any foreign-tenant account line.|test_AC_reporting_cash_events_5_dual_tenant_predicates_reject_hostile_entries
cash-events.6|Generate_cash_flow is the single reporting-owned cash projection used by standalone and package consumers.|test_AC_reporting_cash_events_6_one_projection_serves_every_cash_flow_consumer
cash-events.7|Exact cash identities plus anchored event decisions produce proven output.|test_AC_reporting_cash_events_7_consumer_proof_state_is_explicit
cash-events.8|Each classified or unclassified cash event exposes exact journal-entry, journal-line, source, decision-anchor.|test_AC_reporting_cash_events_8_event_lineage_exposes_ledger_and_decision_anchors
cash-events.12|Anchored statement cash events map LOAN_PRINCIPAL on liabilities to Financing and INVESTMENT_TRADE on assets to Investing.|test_AC_reporting_cash_events_12_statement_balance_sheet_categories_classify
2832.1|Generate_cash_flow classifies system cross_period_gap_plug journal lines as opening_stock_adjustment.|test_AC_reporting_2832_1_cross_period_gap_plug_bridges_as_opening_stock_adjustment|P1
@$be/reporting/test_cash_event_governance.py|P0|done|exact
cash-events.9|Package governance detail projects the exact detector, proof strength, target SHA, issue.|test_AC_reporting_cash_events_9_governance_detail_is_package_owned_and_enforced
cash-events.10|The adversarial cash-event matrix locks non-cash, settlement, transfer, FX, void.|test_AC_reporting_cash_events_10_counterfactual_matrix_is_locked
@$fe/__tests__/homeActionBanner.test.tsx|P1
fe-period-cockpit.6|Home shows at most one action banner.|AC-reporting.fe-period-cockpit.6 picks at most one action: the queue first, then the workflow, then the first upload
fe-period-cockpit.9|Home names the count of the confidence queue and its first item, with a link to that item, above the statement cards.|AC-reporting.fe-period-cockpit.9 names the count and the first item of the queue before a workflow blocker
@$fe/__tests__/homeCoverageStart.test.tsx|P1
fe-period-cockpit.8|In the default view, Home waits for the coverage start of the period end, then requests the income statement, the cash flow and the opening balance sheet of the bounded period only.|AC-reporting.fe-period-cockpit.8 starts the Home period on the coverage start and measures the change from it
fe-period-cockpit.10|Home with an explicit `period=1Y` in the URL requests the income statement and the cash flow of the full preset period, shows no coverage note, does not request `GET /reports/coverage`.|AC-reporting.fe-period-cockpit.10 shows an explicit 1Y in full and bounds All to coverage start
2726.2|When approved statements exist only outside the default `1Y` window, Home and `/reports` display a one-click banner in the dimension bar that jumps the period end to `latest_statement_end`.|AC-reporting.2726.2 shows a one-click banner jumping to the latest statement period when statements precede the default 1Y window
@$be/reporting/test_report_coverage.py|P1|done|exact
2646.1|The readiness of the current package covers the 365 days.|test_AC_reporting_2646_1_first_statement_opening_has_no_coverage_blocker
2646.2|`report_coverage` is the latest opening position of a cash account on or.|test_AC_reporting_2646_2_coverage_start_is_the_latest_cash_opening
2646.3|With 36 approved bank statements, `GET /reports/coverage` runs at most 6 SQL statements.|test_AC_reporting_2646_3_coverage_reads_a_fixed_number_of_queries_at_year_scale
2726.1|`GET /reports/coverage` exposes `latest_statement_end` as the latest approved statement period end on or.|test_AC_reporting_2726_1_coverage_exposes_latest_approved_statement_end
@$be/reporting/test_data_quality_service.py|P1|done|exact
2726.3|Audit Hub `Temporal Continuity Timeline` displays the 12 months ending at the latest statement period end.|test_AC_reporting_2726_3_timeline_anchors_at_latest_statement_period_end
2822.1|Compute_personal_data_quality excludes unapproved Stage-1 statement transactions from Stage-2 Reconciliation & Debt Clearance Purity failures and duplicate RECONCILE_TRANSACTIONS action items.|test_AC_reporting_2822_1_pending_stage1_statement_does_not_fail_reconciliation_purity
2832.2|Compute_personal_data_quality evaluates per-account adjacent statement pairs by materiality.|test_AC_reporting_2832_2_zero_change_gap_verified_and_material_gaps_ranked_by_delta
2564.1|Compute_personal_data_quality calculates the reconciliation ratio from matched_transactions.|test_AC_reporting_2564_1_recon_score_does_not_double_count_auto_accepted
@$fe/__tests__/homeFetchBudget.test.tsx|P1
fe-fetch-budget.1|Home issues each request at most once on a cold mount and reads only its cockpit sources, issues no request for cached data on a second visit, refetches only the two balance sheets for a scope change.|AC-reporting.fe-fetch-budget.1 cold mount issues each request at most once and reads only the cockpit sources
fe-fetch-budget.2|The Home advisor suggestions load off the critical path with a stale time of at least five minutes.|AC-reporting.fe-fetch-budget.2 the advisor suggestions do not block the cockpit and stay cached for five minutes
@-|P1
snapshot-ownership.1|ReportSnapshot and ReportType are published and mapped by reporting.|$t/test_s3_pr_d_structure.py::test_AC_reporting_snapshot_ownership_and_metadata_registration|P0
vocabulary-ownership.1|PersonalReportingFrameworkId, ReportLineId.|$t/test_vocabulary_ownership.py::test_AC_reporting_vocabulary_ownership_1_reporting_owns_wire_enums
framework.2|The same settlement-and-portfolio fixture drives both US-like and HK-like personal report packages, producing framework-specific line mappings, notes bases, source anchors, export metadata.|$be/reporting/test_framework_policy.py::test_AC20_7_1_same_settlement_fixture_drives_us_hk_report_policy_outputs|P0:exact
pipeline.1|Every L2 category — each `AssetType` and each `ManualValuationComponentType`.|$be/reporting/test_framework_policy_coverage.py::test_AC20_8_1_every_asset_type_maps_to_an_l1_line|P0:property
pipeline.2|EPIC-020 declares the three reporting-pipeline layers, each with a locked EPIC-026 tier and its valid proof obligation, confining LLM authority to the LLM-LED layer.|$be/reporting/test_l1_registry_aggregation.py::test_AC20_9_1_framework_balance_sheet_exact_aggregation|P0:property
dry-ssot.2|Shared reporting fixtures are provided by a single `tests/reporting/_report_fixtures` module and reused, with duplicate per-file `test_user_id` fixtures removed.|$be/reporting/test_report_fixtures_shared.py::test_report_fixtures_shared|:exact
balance-sheet.7|Balance sheet equation evaluation does not use circular plugging for CTA, correctly reports is_balanced=False.|$be/reporting/test_falsifiable_balance_sheet.py::test_balance_sheet_cta_and_aggregation_falsifiability
balance-sheet.8|A rounding residual of a multi-currency translation moves into the CTA reserve only.|$be/reporting/test_balance_sheet_translation_rounding.py::test_case_4_shape_balance_sheet_equation_delta_is_exactly_zero
fx.4|Missing report FX rates produce explicit partial warnings for the unconvertible currency.|$be/reporting/test_reporting_fx_fallbacks.py::test_aggregate_balances_missing_fx_skips_unconvertible_currency_with_warning|P0
errors.1|Report-generation failures surface as structured router errors.|$be/reporting/test_reports_errors.py::test_reports_router_errors_extended
errors.2|Each reports endpoint maps a ReportError to a structured HTTP error response.|$be/reporting/test_reports_router_errors.py::test_balance_sheet_report_error
kpis.3|Report output lists the currencies that used the average-rate spot fallback.|$be/reporting/test_reporting_fx_revaluation_integration.py::test_income_statement_includes_average_rate_fallback_warning
package-investment.1|The personal report package defines the investment_performance section as a consumer of the EPIC-017 schedule API.|$t/test_investment_performance_report_contract.py::test_AC5_8_1_personal_report_package_consumes_investment_schedule_contract|P0
integration.1|Multi-currency posted entries generate balanced balance-sheet, income-statement.|$be/integration/test_reporting_e2e.py::test_AC5_15_1_multicurrency_reporting_cycle_reconciles_bs_is_cf|P0
package-document.11|Package readiness validates cumulative balance-sheet and selected-period income against matching ledger periods.|$be/reporting/test_package_period_readiness.py::test_AC_reporting_package_document_11_prior_period_package_lifecycle|:exact
package-document.14|PackageAssembler.evaluate_readiness returns the readiness of assemble for the same arguments.|$be/reporting/test_package_readiness_path.py::test_AC_reporting_package_document_14_readiness_path_equals_full_assembly|P0:exact
package-document.15|One package evaluation runs the current-authority projection at most 2 times.|$be/reporting/test_package_authority_reads.py::test_AC_reporting_package_document_15_one_evaluation_reads_the_authority_projection_at_most_twice|:property
full-year.1|Multi-month CSV statements with reviewed semantic dispositions parse, approve under the balance-chain guard, auto-post.|$be/integration/test_full_year_statement_to_report_e2e.py::test_AC8_15_1_full_year_statement_to_report_ties_out|P0
full-year.2|A high-confidence balance-validated bank statement with no pre-selected account auto-creates+links its asset account, reaches APPROVED.|$be/integration/test_bank_statement_auto_account_post.py::test_AC8_15_2_bank_statement_auto_creates_account_and_posts_with_reviewed_disposition
augmentation.1|A source-labelled ledger input and a superseded manual valuation both reach the report correctly.|$be/integration/test_augmentation_seam_e2e.py::test_AC8_16_1_augmentation_seam_excludes_superseded_without_source_assurance
augmentation.2|A report aggregates only the requesting user's facts.|$be/integration/test_cross_user_report_isolation_e2e.py::test_AC8_16_2_reports_exclude_other_users_entries
lineage.1|GET /api/reports/account-lineage returns the user-scoped posted/reconciled journal lines contributing to an account's balance, each with a journal_line evidence anchor and Decimal-safe signed amounts.|$be/reporting/test_account_lineage.py::test_AC22_3_3_account_lineage_returns_posted_contributing_lines
net-worth-timeseries.3|For the same stored FX rates and the same include_restricted scope, each point of the net worth time-series equals total_assets and total_liabilities of generate_balance_sheet on the point date.|$be/reporting/test_net_worth_timeseries_equivalence.py::test_AC_reporting_net_worth_timeseries_3_daily_points_equal_balance_sheets
net-worth-scope.16|The app generate request names no include_restricted.|$fe/__tests__/reportPackage.test.ts::packageSnapshotRequest builds the generate-snapshot request body and omits an absent currency and the scope
net-worth-scope.21|A data quality action item with score_boost 0 renders.|$fe/__tests__/dataQualityObservatory.test.tsx::#2645 renders an action without a score boost when the boost is zero|P2
api-vectors.1|The serialized GET /api/reports/balance-sheet response recomputed from fixed deterministic inputs equals the committed common/reporting/conformance/vectors.json.|$be/schemas/test_api_response_vectors.py::test_AC_reporting_api_vectors_1_balance_sheet_matches_committed_vector
fe-viz-reports.2|Personal report package renders the `investment_performance` report section from the EPIC-017 schedule API.|$fe/__tests__/portfolioPage.test.tsx::AC5.8.1 renders investment performance report schedule from the schedule API|P0
fe-ia-reports.6|Desktop and mobile smoke covers the `/reports` tabs, the statement cards and a Balance Sheet drill-down.|apps/frontend/playwright/reports-cockpit.spec.ts::${label} shows the report tabs and the statement cards and drills a balance-sheet amount
fe-ia-reports.8|E2E: an amount on the Balance Sheet drills down to its contributing journal lines and on to the source document.|apps/frontend/playwright/epic022-drilldown-journey.spec.ts::${label}: a Balance Sheet amount drills to its contributing line and on to the source document
fe-ia-reports.11|The reusable lineage panel renders evidence nodes as an ordered source-to-report path with per-hop source, confidence.|$fe/__tests__/lineagePanel.test.tsx::AC22.7.2 renders an ordered lineage path with source, confidence, and version badges
fe-ia-reports.13|Desktop and mobile Playwright smoke covers Cash Flow amount drill-down opening the account-lineage drawer.|apps/frontend/playwright/cash-flow-drilldown.spec.ts::${scenario.name} opens account-lineage drawer from a cash-flow amount
fe-remainder-reports.10|Desktop and mobile Playwright smoke covers the Home action banner above the statement cockpit.|apps/frontend/playwright/upload-first-dashboard.spec.ts::${scenario.name} renders the action banner before the statement cockpit|P0
report-integrity.8|A midperiod package retains current decision-backed statement lineage for included movements.|$be/reporting/test_midperiod_source_lineage.py::test_midperiod_source_lineage_preserves_cutoff|P0:exact
cash-events.11|Cash flow bridge fx_effect is calculated independently from foreign-currency cash rate variances.|$be/reporting/test_falsifiable_cash_flow.py::test_multicurrency_cash_bridge_exposes_discrepancy_on_missing_activity
fe-period-cockpit.11|The cached coverage start and every key of `LEDGER_DERIVED_QUERY_KEYS` are stale.|$fe/__tests__/openingBalanceModal.test.tsx::AC-reporting.fe-period-cockpit.11 marks the coverage start and the ledger reads stale after it records opening balances
2617.1|With 100 more users in the database, each of GET /reports/balance-sheet, /reports/income-statement and /reports/cash-flow reads at most 1.25 times the rows that it reads for one user alone, counted from EXPLAIN of its SELECT statements with sequential scans off.|$be/reporting/test_multi_tenant_read_budget.py::test_AC_reporting_2617_1_report_reads_do_not_grow_with_other_tenants|:property
fe-fetch-budget.3|Upload, the attention queue, the Home action banner and the Workbench share one cache entry per request.|$fe/__tests__/sharedQueryCache.test.tsx::AC-reporting.fe-fetch-budget.3 the upload page polls every three seconds while a statement parses and stops when none parses
fe-fetch-budget.4|A successful mutation marks the ledger-derived cached reads stale.|$fe/__tests__/queryClient.test.ts::AC-reporting.fe-fetch-budget.4 marks every ledger-derived read stale after a successful mutation
fe-fetch-budget.6|The shell polls the workflow status every 30 s.|$fe/__tests__/workflowStatusPolling.test.tsx::AC-reporting.fe-fetch-budget.6 polls every 120 s while nothing is pending
2654.1|BalanceSheetResponse lines expose allocation_source_type.|$be/reporting/test_balance_sheet_provenance.py::test_balance_sheet_lines_carry_allocation_metadata_and_response_drops_it|:exact
2664.1|A balanced foreign-currency journal entry with an entry fx_rate and no stored FxRate row either balances in the equation check or reports a named missing-rate cause in run_balance_sheet_diagnostics and GET /reports/data-quality, never an Unclassified discrepancy.|$be/reporting/test_equation_diagnostics.py::test_AC_reporting_2664_1_balanced_usd_entry_without_fx_rate_row_never_reports_unclassified_discrepancy|P0:exact
""",
    ),
    concepts=concepts(
        """
framework_reporting|common/reporting/framework-reporting.md|US-like and HK-like target-backward policy layer for personal report packages.|common/reporting/reporting.md,common/ledger/readme.md,docs/project/EPIC-020.framework-aware-personal-reporting.md|-|reporting|concept
reporting_calculations|common/reporting/readme.md|Financial reports, multi-currency consolidation, calculations.|common/reporting/reporting.md,common/ledger/readme.md,common/pricing/market_data.md|-|reporting|concept
"""
    ),
    governance=[
        GovernanceInitiative(
            id="authoritative-cash-event-projection",
            title="Tenant-safe authoritative cash-event projection",
            issue="https://github.com/wangzitian0/finance_report/issues/1996",
            depends_on=["meta/governance-control-plane"],
            guarantees=[
                GovernanceGuarantee(
                    id="cash-touch-only",
                    statement="Only cash-touch journal events emit cash-flow activity.",
                    affected_acs=["AC-reporting.cash-events.1"],
                    detector="non-cash-events-in-cash-flow",
                    target="0 non-cash events",
                    lock="ci.backend",
                    proof="cash-event-adversarial-oracle",
                    required_proof_strength="value-oracle",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="event-classification",
                    statement="Cash events classify only from exact semantics bound to authoritative producer provenance; caller-supplied semantics and unsupported balance-sheet counterparts fail closed.",
                    affected_acs=["AC-reporting.cash-events.2"],
                    detector="broad-account-type-classification-paths",
                    target="0 broad account-type classification paths",
                    lock="ci.backend",
                    proof="cash-event-classification-oracle",
                    required_proof_strength="value-oracle",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="transfer-neutrality",
                    statement="Internal cash transfers emit zero activity.",
                    affected_acs=["AC-reporting.cash-events.3"],
                    detector="internal-transfer-activity-lines",
                    target="0 internal-transfer activity lines",
                    lock="ci.backend",
                    proof="cash-event-transfer-neutrality",
                    required_proof_strength="value-oracle",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="cash-bridge",
                    statement="The disclosed cash bridge ties exactly.",
                    affected_acs=["AC-reporting.cash-events.4"],
                    detector="cash-bridge-deltas",
                    target="0 unreconciled bridges",
                    lock="ci.backend",
                    proof="cash-event-bridge-oracle",
                    required_proof_strength="value-oracle",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="dual-tenant-isolation",
                    statement="Cash events require both entry and account tenant ownership.",
                    affected_acs=["AC-reporting.cash-events.5"],
                    detector="single-sided-cash-tenant-predicates",
                    target="0 single-sided predicates",
                    lock="ci.backend",
                    proof="cash-event-tenant-query-contract",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="one-projection-owner",
                    statement="One reporting projection serves every cash-flow consumer.",
                    affected_acs=["AC-reporting.cash-events.6"],
                    detector="parallel-cash-projection-owners",
                    target="1 projection owner",
                    lock="ci.backend",
                    proof="cash-event-consumer-contract",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="consumer-proof-state",
                    statement="Consumers receive proven cash identities and anchored events or an explicit unproven state.",
                    affected_acs=["AC-reporting.cash-events.7"],
                    detector="implicit-cash-authority-consumers",
                    target="0 implicit-authority consumers",
                    lock="ci.backend",
                    proof="cash-event-proof-state-contract",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="event-lineage",
                    statement="Every cash event exposes exact ledger anchors and the provenance used by classification.",
                    affected_acs=["AC-reporting.cash-events.8"],
                    detector="cash-events-without-provenance-lineage",
                    target="0 cash events without provenance lineage",
                    lock="ci.backend",
                    proof="cash-event-lineage-oracle",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="exact-governance-detail",
                    statement="Control-plane detail exposes current proof and enforcement facts.",
                    affected_acs=["AC-reporting.cash-events.9"],
                    detector="cash-event-governance-join-gaps",
                    target="0 missing detail facts",
                    lock="ci.backend",
                    proof="governance-detail-lossless-projection",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="counterfactual-lock",
                    statement="The adversarial cash-event matrix remains executable and blocking.",
                    affected_acs=["AC-reporting.cash-events.10"],
                    detector="missing-cash-event-counterfactuals",
                    target="0 missing counterfactuals",
                    lock="ci.backend",
                    proof="cash-event-counterfactual-matrix",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend",
                ),
            ],
        )
    ],
)
