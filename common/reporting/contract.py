"""PackageContract for ``reporting``."""

from __future__ import annotations

from common.meta.package_contract import (
    ContextScope,
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
    depends_on="audit extraction ledger observability platform portfolio pricing reconciliation".split(),
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
_month_end _month_start _normalize_currency _provenance_from_source_type _quantize_money
_quarter_start _signed_amount assemble_framework_balance_sheet
assemble_framework_income_statement build_personal_report_package_traceability_payload
derive_user_framework_policy_result generate_balance_sheet
generate_annualized_income_schedule cash_flow_line_events cash_flow_period
cash_flow_preview generate_cash_flow generate_income_statement get_account_lineage
get_account_trend get_category_breakdown get_net_worth_allocation_schedule
get_net_worth_timeseries income_bucket is_valid_line_for_framework jsonable
package_currency package_dates package_snapshot_csv package_snapshot_document
package_snapshot_response package_snapshot_summary
register_manual_valuation_lines_provider render_balance_sheet_csv render_cash_flow_csv
render_income_statement_csv resolve_line_currency
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
single-owner.1||test_AC_reporting_single_owner_1_has_no_valuation_line_name_copy
dry-ssot.1||test_reporting_calc_extraction
@$be/reporting/test_balance_sheet_opening_balance_gate.py|P1
opening-balance.1||test_AC2_16_4_balance_sheet_warns_when_opening_balance_missing
opening-balance.2||test_AC2_16_4_balance_sheet_clears_warning_once_opening_balance_recorded
opening-balance.3||test_AC2_16_4_net_worth_allocation_surfaces_opening_balance_warning
@$t/test_framework_reporting_epic_contract.py
framework.1||test_AC20_1_1_framework_registry_defines_us_hk_personal_targets
lanes.1||test_AC20_2_1_mece_direction_matrix_declares_distinct_owner_lanes
target.1||test_AC20_3_1_framework_target_contract_is_report_output_backward
policy.1||test_AC20_4_1_policy_matrix_covers_personal_finance_domains
policy.2||test_AC20_5_1_policy_layer_is_read_only_between_facts_and_report
ai.1||test_AC20_6_1_ai_suggestions_require_structured_reviewed_policy_fields
@$be/ai/test_streaming_contract.py
export-envelope.1||test_AC6_33_5_export_envelope_builds_attachment_headers
export-envelope.2||test_AC6_33_6_export_envelope_rejects_unknown_media_type
export-envelope.4||test_AC6_33_9_export_envelope_rejects_unsafe_filename
@$be/reporting/test_reports_router.py
export-envelope.3||test_AC6_33_8_export_response_matches_typed_envelope
balance-sheet.4||test_balance_sheet_endpoint
errors.4||test_income_statement_endpoint|P1
trust-signals.1||test_AC5_16_1_balance_sheet_defaults_to_the_full_scope
trust-signals.2||test_AC5_16_2_cash_flow_response_preserves_fx_warnings
csv-export.1||test_AC5_17_1_cash_flow_export_returns_csv
@$be/reporting/test_reporting.py
balance-sheet.1||test_balance_sheet_equation
income-statement.1||test_income_statement_calculation
income-statement.3||test_income_statement_invalid_range|P1
cash-flow.1||test_cash_flow_statement
cash-flow.2||test_cash_flow_empty_period|P1
kpis.2|Unrealized P&L is reflected in balance-sheet equity.|test_reporting_dashboard_fixture_exact_totals
lineage.2|Each cash-flow line carries its account anchor.|^|P1
provenance.1||test_AC22_13_1_report_amount_lines_expose_normalized_provenance|P1
@$be/reporting/test_reporting_fx.py|P1
balance-sheet.2||test_fx_unrealized_gain_calculation|P0
balance-sheet.3||test_multi_currency_aggregation|P0
income-statement.2||test_income_statement_comprehensive_income
fx.1||test_reporting_fx_fallbacks
fx.2||test_balance_sheet_net_income_fx_fallback
fx.3||test_reports_lazy_resolve_missing_hkd_sgd_from_bridge_rates|P0
2728.1||test_AC_reporting_2728_1_balance_sheet_exposes_native_amount_when_fx_rate_missing
@$e2e/test_personal_financial_report_package.py
balance-sheet.5|A historical as_of_date balance sheet excludes a portfolio position whose ManagedPosition.acquisition_date postdates that as_of_date.|test_personal_financial_report_package_post_merge_journey|P1:property
package-notes.3|The post-merge package proof asserts the notes endpoint, required note IDs.|^
package-traceability.3|The post-merge package proof fails trusted totals.|^
@$be/reporting/test_reporting_net_worth_components.py|P1
balance-sheet.6||test_AC_reporting_balance_sheet_6_valuation_gap_disclosed_in_portfolio_warnings
net-worth-components.1||test_AC11_20_1_retirement_and_benefit_assets_are_restricted_assets_in_balance_sheet
net-worth-components.2||test_AC11_20_2_net_worth_allocation_groups_retirement_and_benefit_assets
layer3.1|The income statement's classification coverage reads Layer 3 APPLIED TransactionClassification rows joined to their category accounts.|test_income_statement_includes_applied_classification_breakdown
layer3.3|Income statement payloads include the applied Layer 3 classification coverage breakdown.|^
net-worth-components.3||test_AC17_14_2_net_worth_allocation_groups_balance_sheet_sources
@$be/api/test_reports_router.py|P1
cash-flow.3||test_account_trend_with_period
cash-flow.4||test_category_breakdown_success
cash-flow.5||test_category_breakdown_with_period
errors.3||test_unauthenticated_access
errors.5|GET /reports/{report_type}/snapshots returns the user's persisted report snapshots.|test_list_report_snapshots_returns_created_snapshots
layer3.2|ReportSnapshot rows are generated and queryable.|^
@$be/reporting/test_cash_flow_preview_payload.py|P1|done|property
cash-flow.6||test_AC_reporting_cash_flow_6_year_scale_preview_is_bounded
cash-flow.7||test_AC_reporting_cash_flow_7_line_events_pages_equal_document|:exact
@$be/reporting/test_income_annualized_router.py|P1
kpis.1|The annualized income KPI endpoint groups the last 12 months of income.|test_annualized_income_endpoint_groups_last_12_month_income|P0
annualized-dashboard.1|GET /api/income/annualized returns {annualized_salary, annualized_bonus, annualized_dividend, annualized_total, currency, as_of} derived from the last 12 months of Income-type journal entries.|^
annualized-dashboard.2||test_restricted_assets_endpoint_returns_latest_locked_holdings
annualized-dashboard.3||test_AC11_8_7_annualized_income_endpoint_converts_mixed_currency_totals
@$be/reporting/test_reporting_extreme_fallbacks.py|P1
kpis.4||test_account_trend_raises_when_prefetched_rate_missing
kpis.5||test_category_breakdown_raises_when_prefetched_rate_missing
kpis.6||test_cash_flow_raises_when_start_date_rate_missing
kpis.7||test_cash_flow_raises_when_end_date_rate_missing
@$be/api/test_personal_report_package_contract.py
package-contract.1||test_AC5_9_1_package_contract_defines_required_sections
package-contract.2||test_AC5_9_2_package_contract_marks_decimal_totals_and_period_semantics
package-annualized.1||test_AC5_11_1_package_contract_marks_annualized_schedule_ready
package-notes.1||test_AC5_12_1_package_notes_endpoint_returns_required_note_taxonomy
package-notes.2||test_AC5_12_2_package_contract_marks_notes_ready
package-traceability.1|The package traceability endpoint returns source-to-ledger anchors per report line.|test_AC5_13_1_package_traceability_endpoint_returns_section_line_anchors
trust-signals.3|Package traceability lines expose source classes, proof level, anchor count.|^
package-traceability.2||test_AC5_13_2_package_traceability_declares_completeness_warnings
package-traceability.4||test_AC5_13_5_package_traceability_returns_dynamic_current_user_identifiers
package-snapshot.1||test_AC5_19_1_package_generate_creates_draft_or_trusted_snapshot
package-snapshot.2||test_AC5_19_2_package_snapshot_get_is_user_scoped_and_immutable
package-snapshot.3|Package JSON and CSV downloads are derived from a saved snapshot.|test_AC_reporting_package_document_4_exports_the_selected_frozen_document
package-document.4|A selected frozen document is the only JSON/CSV export input.|^|:property
package-document.5||test_AC_reporting_package_document_5_trace_and_snapshot_rollback_together
source-anchors.1||test_AC19_10_1_unknown_journal_source_ids_are_not_reported_as_statement_transactions
@$be/reporting/test_financial_logic_audit.py
logic-audit.1||test_AC5_10_1_cash_flow_uses_cumulative_cash_balances
logic-audit.2||test_AC5_10_2_cash_flow_activity_totals_preserve_signs
package-document.8||test_AC_reporting_package_document_8_uses_exact_cash_inputs_not_account_names
@$be/reporting/test_annualized_income_schedule.py
package-annualized.2||test_AC5_11_3_AC11_11_3_annualized_schedule_converts_mixed_currency_totals
package-annualized.3|The reporting-owned annualized section returns annualized salary, bonus, dividend, total income, currency, as-of date.|test_AC11_11_1_AC11_11_2_annualized_schedule_includes_income_and_restricted_treatment
package-annualized.4|The schedule includes ESOP/RSU/stock-option restricted holdings with valuation basis, vesting/unlock metadata, fair value.|^
package-annualized.5||test_AC11_11_4_annualized_schedule_surfaces_structured_valuation_basis
@$be/reporting/test_report_traceability_linear.py|P1
package-traceability.5||test_AC_reporting_package_traceability_5_output_equals_pre_change_golden
package-traceability.6||test_AC_reporting_package_traceability_6_builder_is_linear_in_contributions|:property
@$be/reporting/test_package_preview_payload.py|P1|done|property
package-traceability.7||test_AC_reporting_package_traceability_7_year_scale_preview_is_bounded
package-traceability.8||test_AC_reporting_package_traceability_8_evidence_pages_equal_snapshot|:exact
@$be/reporting/test_package_preview_policy_and_cash_flow.py|P1
package-traceability.9||test_AC_reporting_package_traceability_9_year_scale_preview_with_categories_is_bounded|:property
package-traceability.10||test_AC_reporting_package_traceability_10_policy_decision_pages_equal_snapshot
package-traceability.11||test_AC_reporting_package_traceability_11_cash_flow_event_pages_equal_snapshot
@$be/reporting/test_package_document.py
package-document.1||test_AC_reporting_package_document_1_requires_typed_delivery_sections
package-document.2||test_AC_reporting_package_document_2_has_one_assembler_and_no_live_package_export
package-document.3||test_AC_reporting_package_document_3_trust_is_one_trace_decision_fold
package-document.6||test_AC_reporting_package_document_6_producer_and_consumer_closure
package-document.7||test_AC_reporting_package_document_7_manifest_folds_only_typed_contributions
package-document.9||test_AC_reporting_package_document_9_requires_exact_decision_coordinates
package-document.10||test_AC_reporting_package_document_10_reconstructs_exact_decision_coordinates
package-document.13||test_AC_reporting_package_document_13_single_pass_traceability_and_unrealized_fx_reuse
2466.1||test_AC_reporting_2466_1_every_cash_flow_proof_reason_has_its_own_text|P1
2623.1||test_AC_reporting_2623_1_system_accounts_receive_l1_policy_mappings|P1
2667.1||test_AC_reporting_2667_1_pre_2655_frozen_package_keeps_decision_ref_and_locks_bound_defaults|P1
@$fe/__tests__/personalReportPackagePage.test.tsx|P1
package-document.12||AC-reporting.package-document.12 previews and generates the selected month through the page|P0
net-worth-scope.15||#2645 labels the package net worth from the recorded scope and names each excluded class
net-worth-scope.17||#2645 shows no bare net worth for a snapshot frozen before the scope record|P0
net-worth-scope.23||#2645 labels the package net worth from the scope that the document context records
fe-viz-reports.1|The annualized income figures show in the Full package tab from the package document.|AC5.11.2 renders annualized income schedule values and restricted treatment|P0
fe-viz-reports.5|Frontend personal package page renders annualized income totals and restricted treatment from the schedule endpoint.|^|P0
fe-viz-reports.3||AC5.9.3 renders personal package contract sections from API|P0
fe-viz-reports.4||AC5.9.4 renders export contract metadata
fe-viz-reports.6||AC5.12.3 renders package notes and disclosure basis|P0
fe-viz-reports.7|Frontend personal package page renders source, ledger, review.|AC5.13.3 AC5.16.3 AC5.16.4 renders traceability appendix source, ledger, review, and identifiers|P0
fe-viz-reports.10|Personal report package traceability renders concrete source and ledger identifiers.|^|P0
fe-viz-reports.11||AC5.17.2 downloads package CSV through authenticated apiDownload|P0
fe-viz-reports.12||AC5.19.4 generates and downloads package snapshots|P0
fe-ia-reports.14||AC22.8.1 titles package sections with human labels, not developer snake_case identifiers
fe-ia-reports.15||AC22.8.2 AC22.13.3 renders a readable package cover and linked table of contents
fe-ia-reports.16||AC20.6.1 AC22.8.3 AC22.13.3 requires explicit framework selection before loading framework-scoped package output
fe-ia-reports.23||AC22.19.1 renders the loaded package with reader-first labels before proof internals
fe-ia-reports.24||AC22.19.2 keeps proof and policy internals in keyboard-reachable audit details
fe-ia-reports.25||AC22.19.3 keeps export proof metadata behind a print-hidden export audit disclosure
fe-remainder-reports.1|The report package traceability surface exposes a lineage panel from at least one report traceability row.|AC18.9.4 AC18.9.5 AC18.9.6 opens an Evidence Graph lineage panel from report traceability|P2
fe-remainder-reports.2|The lineage panel renders source document, extracted record, atomic fact, ledger entry, ledger line.|^|P2
fe-remainder-reports.3|Tests cover report line to source document navigation and source document to impacted ledger/report navigation.|^|P2
fe-remainder-reports.11||AC19.5.4 renders package readiness before report package output
fe-remainder-reports.12||AC19.5.5 renders non-blocked readiness states without blocker cards
fe-remainder-reports.14||AC19.9.2 renders decision authority coverage before traceability details|P0
fe-fetch-budget.5||AC-reporting.fe-fetch-budget.5 the Reports hub and the package page share one preview request
fe-fetch-budget.7||AC-reporting.fe-fetch-budget.7 loads the details of a traceability line only after the user opens the line
fe-fetch-budget.9||AC-reporting.fe-fetch-budget.9 loads the policy decisions only after the user opens the audit details
@$be/reporting/test_year_scale_reporting.py|P1
year-scale.1||test_AC5_20_year_scale_reporting_ties_out_within_budget
net-worth-timeseries.4||test_AC_reporting_net_worth_timeseries_4_six_month_daily_series_within_budget
@$be/reporting/test_income_typed_currency.py|P2
income-typed.1||test_AC5_32_1_currency_code_type_validates_and_normalizes
income-typed.2||test_AC5_32_2_annualized_income_totals_is_typed_intermediate
income-typed.3||test_AC5_32_3_resolve_line_currency_uses_canonical_fallback_chain
income-typed.4||test_AC5_32_4_fx_conversion_error_response_model_declared
income-typed.5||test_AC5_32_5_normalize_currency_code_is_shared_helper
income-typed.6||test_AC5_32_6_endpoint_returns_normalized_currency_for_soft_base_config
@$be/api/test_typed_contract_sweep.py|P2
snapshots-typed.1||test_AC5_36_1_report_snapshots_unknown_type_returns_422
snapshots-typed.2||test_AC5_36_2_report_snapshots_valid_type_returns_typed_list
@$be/reporting/test_reporting_shift_left.py
journeys.1||test_balance_sheet_accounting_equation_articulation
journeys.2||test_income_statement_revenues_expenses_net_income
journeys.3||test_cash_flow_bridge_reconciliation
journeys.4||test_multi_period_reporting_and_cta_adjustment|P1
@$be/reporting/test_net_worth_timeseries.py|P1
net-worth-timeseries.1||test_net_worth_timeseries_router
net-worth-timeseries.2||test_net_worth_timeseries_uses_historical_fx_per_point
net-worth-timeseries.5||test_AC_reporting_net_worth_timeseries_5_monthly_series_starts_at_first_month_with_value
@$be/reporting/test_net_worth_one_definition.py
net-worth-scope.1||test_AC_reporting_net_worth_scope_1_every_surface_reads_one_net_worth
net-worth-scope.2||test_AC_reporting_net_worth_scope_2_manual_valuations_stay_out_of_fx_and_cta
net-worth-scope.3||test_AC_reporting_net_worth_scope_3_balance_sheet_names_each_excluded_class_and_amount
net-worth-scope.8||test_AC_reporting_net_worth_scope_8_allocation_sources_carry_no_link|P1
net-worth-scope.9||test_AC_reporting_net_worth_scope_9_excluded_valuation_without_fx_rate_does_not_fail_the_report
net-worth-scope.10||test_AC_reporting_net_worth_scope_10_included_valuation_without_fx_rate_still_fails_the_report
net-worth-scope.11||test_AC_reporting_net_worth_scope_11_package_discloses_each_excluded_class
net-worth-scope.12||test_AC_reporting_net_worth_scope_12_generate_without_scope_reads_the_package_default|P1
net-worth-scope.13||test_AC_reporting_net_worth_scope_13_data_quality_stays_available_without_a_valuation_fx_rate|P1
net-worth-scope.14||test_AC_reporting_net_worth_scope_14_package_lists_a_restricted_holding_without_fx_rate|P1
net-worth-scope.18||test_AC_reporting_net_worth_scope_18_data_quality_reads_the_liquid_check_after_an_fx_error|P1
net-worth-scope.19||test_AC_reporting_net_worth_scope_19_data_quality_raises_other_errors|P1
net-worth-scope.20||test_AC_reporting_net_worth_scope_20_package_records_its_scope
net-worth-scope.22||test_AC_reporting_net_worth_scope_22_main_shape_document_keeps_its_decision_version
@$fe/__tests__/uiGapAudit.netWorthTimeSeries.test.tsx|P2
net-worth-scope.4||#2645 requests the series in the restricted-holdings scope of the dimension bar|P1
fe-viz-reports.28|The net worth chart of the Balance sheet tab renders an ECharts line chart with a date X-axis and a net-worth Y-axis.|AC5.7.2/AC5.7.6 mounts an ECharts-backed net worth line chart
fe-viz-reports.31|A frontend unit test mounts the net worth chart and asserts that the chart container exists.|^
fe-viz-reports.29||AC5.7.4 reads the period of the dimension bar and draws months for a period longer than one quarter
fe-viz-reports.30||AC5.7.5 renders an empty state when fewer than two points exist
fe-viz-reports.34||caches each period so a revisit within the stale time sends no request|P1
@$fe/__tests__/dashboardPage.test.tsx|P1
net-worth-scope.5||AC11.8.5 defaults to the full net worth and labels each excluded class when restricted holdings are excluded
fe-report-surfaces.1||AC16.12.1 shows loading state before dashboard data resolves|P2
fe-report-surfaces.2||AC16.12.2 renders error fallback and retry action on failure|P2
fe-report-surfaces.3|Home renders the dimension bar and the three statement cards with the live metrics of the period.|AC16.12.3 AC22.1.2 renders the dimension bar and the three statement cards of the period|P2
fe-ia-reports.1|The authenticated Home renders the dimension bar, the three statement cards with key numbers.|^
fe-report-surfaces.4||AC16.12.4 shows zero metrics and no line list for an empty period|P2
fe-report-surfaces.5|Home asks a user without a source to upload the first statement in its one action banner.|AC22.16.1 AC16.12.17 AC16.12.18 asks a new user to upload the first statement|P2
fe-report-surfaces.6|The Home upload action links to the `/upload` page in one click.|^|P2
fe-ia-reports.20|The Home upload action targets `/upload`.|^
fe-report-surfaces.7||AC16.12.19 hides the action banner when nothing needs attention|P2
fe-ia-reports.7||AC22.4.4 keeps Home lean: one cockpit and no analytics panel or duplicate metric block
fe-ia-reports.9|Home surfaces at most one primary next action.|AC22.16.2 AC22.5.6 routes the confirmation count to the one /audit queue
fe-ia-reports.21|Home presents one confidence-ranked attention entry point.|^
fe-viz-reports.27||renders the advisor brief after the statement cards and keeps the cockpit when suggestions fail
fe-remainder-reports.4|Home shows the workflow next action only as one action banner.|AC19.4.3 shows one action banner that follows the workflow next action|P0
fe-remainder-reports.6|The Home action banner follows the `href` and the label of `workflow.status.next_action`.|^|P0
fe-remainder-reports.5||AC19.4.2 AC16.16.1 renders the action banner before the dimension bar and the statement cards|P0
fe-remainder-reports.9||AC19.4.6 keeps the statement cards visible when the workflow status fails|P0
@$fe/__tests__/balanceSheetPage.test.tsx|P1
net-worth-scope.6||#2645 shows manual valuations on their own equity line, never in the FX and CTA line
net-worth-scope.7||#2645 names each class and amount that the scope without restricted holdings excludes
api-vectors.2|The frontend balance-sheet page test consumes the committed reporting conformance vector verbatim as its mock data.|AC16.14.2 / test_AC8_13_48 renders string totals and refetches by date
fe-report-surfaces.11|The Balance sheet tab renders totals and account sections on successful fetch.|^|P2
fe-viz-reports.8|Balance sheet page exposes the restricted-holdings include toggle and renders equation component detail.|^|P0
fe-viz-reports.9|Balance sheet, income statement.|^|P0
fe-report-surfaces.10||AC16.14.1 renders loading and error retry states|P2
fe-report-surfaces.12||AC16.14.3 toggles tree expansion controls|P2
2728.2||AC-reporting.2728.2 labels Processing as Transfers in transit and discloses foreign-currency native balances
2728.3||AC-reporting.2728.3 opens the source drill-down from either the account name or the dotted-underlined amount
2654.2||AC-reporting.2654.2 routes manual valuation lines to /portfolio?panel=evidence without calling account-lineage
@$e2e/test_brokerage_upload_to_portfolio_value.py
portfolio-valuation-gate.1||test_portfolio_valuation_gate_ignores_unrelated_negative_asset_lines
portfolio-valuation-gate.2||test_portfolio_valuation_gate_failure_diagnostics_are_actionable
@$fe/__tests__/reportsCockpit.test.tsx|P1
fe-report-surfaces.8|`/reports` renders the tabs Overview, Balance sheet, Income statement, Cash flow and Full package.|AC-reporting.fe-period-cockpit.3 renders the five report tabs, selects the tab of the URL, and keeps the dimensions in each tab link|P2
fe-ia-reports.3|Cash Flow and the Personal Report Package are tabs of `/reports` next to the Balance sheet and Income statement tabs.|^
fe-period-cockpit.3|`/reports` shows the three statements and the report package as tabs of one page.|^
fe-report-surfaces.9||AC16.12.12 states the accounting equation on the Balance sheet tab|P2
fe-ia-reports.2||AC22.3.1 leads with the three statement cards and their live figures for the period
fe-ia-reports.18||AC22.9.1 keeps every Overview link inside the everyday surfaces, not the Advanced reconciliation surface
fe-viz-reports.32||AC5.37.1 renders trust-first readiness before report cards
fe-viz-reports.33||AC5.37.2 preserves report navigation when readiness is unavailable|-|non-goals-not-budgeting-app
@$fe/__tests__/incomeStatementPage.test.tsx|P2
fe-report-surfaces.13||AC16.14.4 renders loading and error retry states
fe-report-surfaces.14||AC16.14.5 / test_AC8_13_48 renders string KPI cards and category lists
fe-report-surfaces.15||AC16.14.6 supports selecting and clearing tags
@$fe/__tests__/cashFlowPage.test.tsx|P2
fe-report-surfaces.16||AC16.14.7 renders loading and error retry states
fe-report-surfaces.17||AC16.14.8 / test_AC8_13_48 renders string summary and activity sections
fe-report-surfaces.18||AC16.14.9 renders sankey chart when summary exists
fe-ia-reports.10||AC22.7.1 drills a cash-flow amount down to its account lineage|P1
fe-ia-reports.12||AC22.7.3 flags cash that does not tie (beginning + net != ending)|P1
fe-fetch-budget.8||AC-reporting.fe-fetch-budget.8 loads the events of a cash-flow line only after the user expands the line|P1
@$fe/__tests__/chartsComponents.test.tsx|P2
fe-report-surfaces.19||AC16.19.10 bar chart and pie chart render labels and filtered segments
2548.3||AC-reporting.2548.3 renders axis scale bounds, formatted values, and percentage shares across chart components|P1
@$fe/__tests__/sankeyChartComponent.test.tsx|P2
fe-report-surfaces.21||AC16.21.7 renders empty-state option when no series data is provided
fe-report-surfaces.22||AC16.21.8 recomputes theme-driven colors on root attribute change
@$fe/__tests__/balanceSheetDrilldown.test.tsx|P1
fe-ia-reports.4||AC22.3.4 lists contributing journal lines and opens the lineage chain for one
fe-ia-reports.5||AC22.3.5 shows an empty state when no transactions contribute
@$fe/__tests__/reportPageShell.test.tsx|P1
fe-viz-reports.13||AC5.33.1 renders title, description, toolbar, and body content
fe-viz-reports.14||AC5.33.2 shows loading skeleton while loading
fe-viz-reports.15||AC5.33.3 shows error message and retries on click
@$fe/__tests__/reportToolbar.test.tsx|P1
fe-viz-reports.16||AC5.33.4 renders the AI prompt and the caller-provided export control, without a Home link
fe-viz-reports.17||AC5.33.5 links to chat with url-encoded prompt
@apps/frontend/playwright/report-readiness.spec.ts|P1
fe-ia-reports.17|Desktop and mobile Playwright smoke covers report-package framework selection, cover, table of contents, readiness.|${scenario.name} renders cover, contents, and readiness before package output
fe-remainder-reports.13|Report readiness has route-level Playwright smoke coverage.|^
@$fe/__tests__/reportFilters.test.tsx|P1
fe-viz-reports.18||AC-reporting.fe-period-cockpit.2 sets the preset and steps the period through the URL
fe-viz-reports.19||AC5.34.2 shows the base currency until the URL names one and writes the selected currency to the URL
@$fe/__tests__/useReportFilters.test.ts|P1
fe-viz-reports.20|`useReportFilters` reads the tab, period, end, currency and scope from the URL and falls back to the defaults on invalid values.|AC-reporting.fe-period-cockpit.2 reads the dimensions from the URL and falls back to defaults on invalid values
fe-viz-reports.23|The redirects of the old report routes keep their query.|^
fe-viz-reports.21||AC-reporting.fe-period-cockpit.2 builds tab links that keep the dimension query
fe-viz-reports.22|`useReportFilters` writes each dimension change to the URL and omits default values.|AC-reporting.fe-period-cockpit.2 writes each dimension change to the URL and omits default values
fe-period-cockpit.2|The period, the period end, the currency and the restricted-holdings scope live only in the URL.|^
fe-period-cockpit.1||AC-reporting.fe-period-cockpit.1 moves a period back and forward by one period length and stops at today
fe-period-cockpit.7||AC-reporting.fe-period-cockpit.7 starts only the default view and All no earlier than the coverage start
@$fe/__tests__/useStatementCockpit.test.ts|P1
fe-viz-reports.24||AC5.35.1 reads the four statement sources of the dimension-bar period
fe-viz-reports.25||AC5.35.2 normalizes missing statement fields to empty lists, zero decimal strings and typed warnings
fe-viz-reports.26||AC5.35.3 surfaces the first error and a retry that refetches only the failed source
@$fe/__tests__/homeStatements.test.tsx|P1
fe-ia-reports.26||deep-links each of the three statements to its report tab and keeps the period
fe-period-cockpit.4||AC-reporting.fe-period-cockpit.4 shows the live metrics of the period on each statement card
fe-period-cockpit.5||AC-reporting.fe-period-cockpit.5 switches the statement with the segmented control and drills a row into its source transactions
@$be/reporting/test_report_integrity.py
report-integrity.1||test_processing_survives_framework_reporting
report-integrity.2||test_opening_stock_is_beginning_cash
report-integrity.3||test_midperiod_opening_is_explicit_incomplete_coverage
report-integrity.4||test_posted_categories_survive_framework_mapping
report-integrity.5||test_uncategorized_history_is_not_investment_activity
report-integrity.6||test_archiving_preserves_historical_reports
report-integrity.7||test_persisted_package_integrity
@$be/reporting/test_cash_event_projection.py
cash-events.1||test_AC_reporting_cash_events_1_only_cash_touch_events_are_classified
cash-events.2||test_AC_reporting_cash_events_2_event_classification_is_authoritative
cash-events.3||test_AC_reporting_cash_events_3_internal_transfers_are_neutral
cash-events.4||test_AC_reporting_cash_events_4_cash_bridge_ties_exactly
cash-events.5||test_AC_reporting_cash_events_5_dual_tenant_predicates_reject_hostile_entries
cash-events.6||test_AC_reporting_cash_events_6_one_projection_serves_every_cash_flow_consumer
cash-events.7||test_AC_reporting_cash_events_7_consumer_proof_state_is_explicit
cash-events.8||test_AC_reporting_cash_events_8_event_lineage_exposes_ledger_and_decision_anchors
cash-events.12||test_AC_reporting_cash_events_12_statement_balance_sheet_categories_classify
2832.1||test_AC_reporting_2832_1_cross_period_gap_plug_bridges_as_opening_stock_adjustment|P1
@$be/reporting/test_cash_event_governance.py
@$fe/__tests__/homeActionBanner.test.tsx|P1
fe-period-cockpit.6||AC-reporting.fe-period-cockpit.6 picks at most one action: the queue first, then the workflow, then the first upload
fe-period-cockpit.9||AC-reporting.fe-period-cockpit.9 names the count and the first item of the queue before a workflow blocker
@$fe/__tests__/homeCoverageStart.test.tsx|P1
fe-period-cockpit.8||AC-reporting.fe-period-cockpit.8 starts the Home period on the coverage start and measures the change from it
fe-period-cockpit.10||AC-reporting.fe-period-cockpit.10 shows an explicit 1Y in full and bounds All to coverage start
2726.2||AC-reporting.2726.2 shows a one-click banner jumping to the latest statement period when statements precede the default 1Y window
@$be/reporting/test_report_coverage.py|P1
2646.1||test_AC_reporting_2646_1_first_statement_opening_has_no_coverage_blocker
2646.2||test_AC_reporting_2646_2_coverage_start_is_the_latest_cash_opening
2646.3||test_AC_reporting_2646_3_coverage_reads_a_fixed_number_of_queries_at_year_scale
2726.1||test_AC_reporting_2726_1_coverage_exposes_latest_approved_statement_end
@$be/reporting/test_data_quality_service.py|P1
2726.3||test_AC_reporting_2726_3_timeline_anchors_at_latest_statement_period_end
2822.1||test_AC_reporting_2822_1_pending_stage1_statement_does_not_fail_reconciliation_purity
2832.2||test_AC_reporting_2832_2_zero_change_gap_verified_and_material_gaps_ranked_by_delta
2564.1||test_AC_reporting_2564_1_recon_score_does_not_double_count_auto_accepted
@$fe/__tests__/homeFetchBudget.test.tsx|P1
fe-fetch-budget.1||AC-reporting.fe-fetch-budget.1 cold mount issues each request at most once and reads only the cockpit sources
fe-fetch-budget.2||AC-reporting.fe-fetch-budget.2 the advisor suggestions do not block the cockpit and stay cached for five minutes
@$t/test_s3_pr_d_structure.py
snapshot-ownership.1||test_AC_reporting_snapshot_ownership_and_metadata_registration
@$t/test_vocabulary_ownership.py|P1
vocabulary-ownership.1||test_AC_reporting_vocabulary_ownership_1_reporting_owns_wire_enums
@$be/reporting/test_framework_policy.py
framework.2||test_AC20_7_1_same_settlement_fixture_drives_us_hk_report_policy_outputs
@$be/reporting/test_framework_policy_coverage.py|P0|done|property
pipeline.1||test_AC20_8_1_every_asset_type_maps_to_an_l1_line
@$be/reporting/test_l1_registry_aggregation.py|P0|done|property
pipeline.2||test_AC20_9_1_framework_balance_sheet_exact_aggregation
@$be/reporting/test_report_fixtures_shared.py|P1
dry-ssot.2||test_report_fixtures_shared
@$be/reporting/test_falsifiable_balance_sheet.py|P1
balance-sheet.7||test_balance_sheet_cta_and_aggregation_falsifiability
@$be/reporting/test_balance_sheet_translation_rounding.py|P1
balance-sheet.8||test_case_4_shape_balance_sheet_equation_delta_is_exactly_zero
@$be/reporting/test_reporting_fx_fallbacks.py
fx.4||test_aggregate_balances_missing_fx_skips_unconvertible_currency_with_warning
@$be/reporting/test_reports_errors.py|P1
errors.1||test_reports_router_errors_extended
@$be/reporting/test_reports_router_errors.py|P1
errors.2||test_balance_sheet_report_error
@$be/reporting/test_reporting_fx_revaluation_integration.py|P1
kpis.3||test_income_statement_includes_average_rate_fallback_warning
@$t/test_investment_performance_report_contract.py
package-investment.1||test_AC5_8_1_personal_report_package_consumes_investment_schedule_contract
@$be/integration/test_reporting_e2e.py
integration.1||test_AC5_15_1_multicurrency_reporting_cycle_reconciles_bs_is_cf
@$be/reporting/test_package_period_readiness.py|P1
package-document.11||test_AC_reporting_package_document_11_prior_period_package_lifecycle
@$be/reporting/test_package_readiness_path.py
package-document.14||test_AC_reporting_package_document_14_readiness_path_equals_full_assembly
@$be/reporting/test_package_authority_reads.py|P1|done|property
package-document.15||test_AC_reporting_package_document_15_one_evaluation_reads_the_authority_projection_at_most_twice
@$be/integration/test_full_year_statement_to_report_e2e.py
full-year.1||test_AC8_15_1_full_year_statement_to_report_ties_out
@$be/integration/test_bank_statement_auto_account_post.py|P1
full-year.2||test_AC8_15_2_bank_statement_auto_creates_account_and_posts_with_reviewed_disposition
@$be/integration/test_augmentation_seam_e2e.py|P1
augmentation.1||test_AC8_16_1_augmentation_seam_excludes_superseded_without_source_assurance
@$be/integration/test_cross_user_report_isolation_e2e.py|P1
augmentation.2||test_AC8_16_2_reports_exclude_other_users_entries
@$be/reporting/test_account_lineage.py|P1
lineage.1||test_AC22_3_3_account_lineage_returns_posted_contributing_lines
@$be/reporting/test_net_worth_timeseries_equivalence.py|P1
net-worth-timeseries.3||test_AC_reporting_net_worth_timeseries_3_daily_points_equal_balance_sheets
@$fe/__tests__/reportPackage.test.ts|P1
net-worth-scope.16||packageSnapshotRequest builds the generate-snapshot request body and omits an absent currency and the scope
@$fe/__tests__/dataQualityObservatory.test.tsx|P2
net-worth-scope.21||#2645 renders an action without a score boost when the boost is zero
@$be/schemas/test_api_response_vectors.py|P1
api-vectors.1||test_AC_reporting_api_vectors_1_balance_sheet_matches_committed_vector
@$fe/__tests__/portfolioPage.test.tsx
fe-viz-reports.2||AC5.8.1 renders investment performance report schedule from the schedule API
@apps/frontend/playwright/reports-cockpit.spec.ts|P1
fe-ia-reports.6||${label} shows the report tabs and the statement cards and drills a balance-sheet amount
@apps/frontend/playwright/epic022-drilldown-journey.spec.ts|P1
fe-ia-reports.8||${label}: a Balance Sheet amount drills to its contributing line and on to the source document
@$fe/__tests__/lineagePanel.test.tsx|P1
fe-ia-reports.11||AC22.7.2 renders an ordered lineage path with source, confidence, and version badges
@apps/frontend/playwright/cash-flow-drilldown.spec.ts|P1
fe-ia-reports.13||${scenario.name} opens account-lineage drawer from a cash-flow amount
@apps/frontend/playwright/upload-first-dashboard.spec.ts
fe-remainder-reports.10||${scenario.name} renders the action banner before the statement cockpit
@$be/reporting/test_midperiod_source_lineage.py
report-integrity.8||test_midperiod_source_lineage_preserves_cutoff
@$be/reporting/test_falsifiable_cash_flow.py|P1
cash-events.11||test_multicurrency_cash_bridge_exposes_discrepancy_on_missing_activity
@$fe/__tests__/openingBalanceModal.test.tsx|P1
fe-period-cockpit.11||AC-reporting.fe-period-cockpit.11 marks the coverage start and the ledger reads stale after it records opening balances
@$be/reporting/test_multi_tenant_read_budget.py|P1|done|property
2617.1||test_AC_reporting_2617_1_report_reads_do_not_grow_with_other_tenants
@$fe/__tests__/sharedQueryCache.test.tsx|P1
fe-fetch-budget.3||AC-reporting.fe-fetch-budget.3 the upload page polls every three seconds while a statement parses and stops when none parses
@$fe/__tests__/queryClient.test.ts|P1
fe-fetch-budget.4||AC-reporting.fe-fetch-budget.4 marks every ledger-derived read stale after a successful mutation
@$fe/__tests__/workflowStatusPolling.test.tsx|P1
fe-fetch-budget.6||AC-reporting.fe-fetch-budget.6 polls every 120 s while nothing is pending
@$be/reporting/test_balance_sheet_provenance.py|P1
2654.1||test_balance_sheet_lines_carry_allocation_metadata_and_response_drops_it
@$be/reporting/test_equation_diagnostics.py
2664.1||test_AC_reporting_2664_1_balanced_usd_entry_without_fx_rate_row_never_reports_unclassified_discrepancy
""",
    ),
    concepts=concepts(
        """
framework_reporting|common/reporting/framework-reporting.md|US-like and HK-like target-backward policy layer for personal report packages.|common/reporting/reporting.md,common/ledger/readme.md,docs/project/EPIC-020.framework-aware-personal-reporting.md|-|reporting|concept
reporting_calculations|common/reporting/readme.md|Financial reports, multi-currency consolidation, calculations.|common/reporting/reporting.md,common/ledger/readme.md,common/pricing/market_data.md|-|reporting|concept
"""
    ),
)
