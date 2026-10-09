"""The ``reporting`` package's machine-checkable :class:`PackageContract`.

This contract records the reporting-domain cutover boundary for Stage 4 of the
package migration umbrella (#1416, issue #1424): reporting is the
calculation-over-ledger package, declares its building blocks with
``units=[Unit(kind=...)]``, and — since the #1666 physical fold — implements
at ``apps/backend/src/reporting/{base,extension,data}``.

Scope correction (2026-07-06): ``manual_valuation.py`` belongs to the pricing
cutover (#1610). Reporting keeps report assembly;
pricing owns valuation-observation staleness facts. Pending that cutover,
reporting reaches manual valuation and the FX conversion service through
composition-root-injected ports (``register_manual_valuation_lines_provider``
/ ``register_fx_gateway``), never by importing the ``services/`` remainder.

Status flip (migration closeout wave 2, #1663): the roadmap's first ACs
(opening-balance gate + the full EPIC-020 framework-reporting set) carry only
``proof_kind`` in ``{exact, property}``, both valid under ``CODE-ONLY`` — so
the package ships ``active``/``CODE-ONLY`` here.

#1674 contract-honesty audit (2026-07-09): declare a dependency only with its
first real import. ``extraction`` supplies decision-backed statement
contributions to package assembly; ``config``/``platform`` remain undeclared
until a real import exists.
"""

from __future__ import annotations

from common.meta.package_contract import (
    ac,
    ConceptRecord,
    ContextRelation,
    ContextScope,
    GovernanceGuarantee,
    GovernanceInitiative,
    Invariant,
    Kind,
    PackageContract,
    Unit,
)

# fmt: off
CONTRACT = PackageContract(
    name="reporting",
    status="active",
    tier="CODE-ONLY",
    depends_on=[
        "audit",
        # extraction: package assembly reads its public statement-contribution
        # DTO, while the appendix renders that DTO without reading extraction ORM.
        "extraction",
        "ledger",
        "observability",
        "platform",
        # portfolio: the market-value adjustment lines read holdings via the
        # published PortfolioService (was services.portfolio before #1643).
        "portfolio",
        "pricing",
        "reconciliation",
    ],
    context=ContextScope(
        purpose="Own deterministic financial report assembly, framework disclosure, and frozen report snapshots over trusted facts from other contexts.",
        in_scope=[
            "financial statement and net-worth calculation views",
            "ReportSnapshot, report-line, framework-policy, readiness, and disclosure language",
            "report-package assembly and traceability of the exact facts a report freezes",
        ],
        out_of_scope=[
            "source-document parsing, ledger posting, position accounting, matching, or valuation resolution",
            "shared financial value/assurance ownership and generic telemetry or persistence substrate",
            "cross-domain workflow execution and user-facing delivery routing",
        ],
    ),
    relationships=[
        ContextRelation(
            provider="audit",
            consumer="reporting",
            mode="published-language",
            reason="Uses audit monetary, source-type, and assurance language for report calculations and disclosure.",
        ),
        ContextRelation(
            provider="extraction",
            consumer="reporting",
            mode="projection",
            reason="Reads statement contributions and source-fact projections without owning document lifecycle.",
        ),
        ContextRelation(
            provider="ledger",
            consumer="reporting",
            mode="projection",
            reason="Reads posted ledger and account projections without creating or changing journal facts.",
        ),
        ContextRelation(
            provider="observability",
            consumer="reporting",
            mode="published-language",
            reason="Uses published safe logging and error-identification language for report generation diagnostics.",
        ),
        ContextRelation(
            provider="platform",
            consumer="reporting",
            mode="composition",
            reason="Uses platform persistence mixins and request-error helpers without owning the substrate.",
        ),
        ContextRelation(
            provider="portfolio",
            consumer="reporting",
            mode="projection",
            reason="Reads portfolio performance and holdings projections for report schedules without owning positions.",
        ),
        ContextRelation(
            provider="pricing",
            consumer="reporting",
            mode="projection",
            reason="Reads decision-backed valuation and FX-resolution contributions without resolving prices itself.",
        ),
        ContextRelation(
            provider="reconciliation",
            consumer="reporting",
            mode="projection",
            reason="Reads reconciliation readiness and transfer-match state for report disclosure without making matches.",
        ),
    ],
    roles=["base", "extension", "data"],
    units=[
        # ── base (package-owned vocabulary plus delivery-only response DTOs) ──
        Unit(
            name="PersonalReportingFrameworkId",
            kind=Kind.VALUE_OBJECT,
            module="base/types.py",
        ),
        Unit(
            name="ReportLineId",
            kind=Kind.VALUE_OBJECT,
            module="base/types.py",
        ),
        Unit(
            name="PolicyDimension",
            kind=Kind.VALUE_OBJECT,
            module="base/types.py",
        ),
        Unit(name="ReportLine", kind=Kind.VALUE_OBJECT),
        Unit(name="BalanceSheetResponse", kind=Kind.VALUE_OBJECT),
        Unit(name="IncomeStatementResponse", kind=Kind.VALUE_OBJECT),
        Unit(
            name="CashFlowItem",
            kind=Kind.VALUE_OBJECT,
            module="base/cash_flow_types.py",
        ),
        Unit(
            name="CashFlowResponse",
            kind=Kind.VALUE_OBJECT,
            module="base/cash_flow_types.py",
        ),
        Unit(
            name="CashFlowSummary",
            kind=Kind.VALUE_OBJECT,
            module="base/cash_flow_types.py",
        ),
        Unit(name="FrameworkPolicyDecision", kind=Kind.VALUE_OBJECT),
        Unit(name="FrameworkPolicyGap", kind=Kind.VALUE_OBJECT),
        Unit(name="FrameworkPolicyMatrix", kind=Kind.VALUE_OBJECT),
        Unit(name="PeriodSpan", kind=Kind.VALUE_OBJECT),
        Unit(name="AnnualizedIncomeTotals", kind=Kind.VALUE_OBJECT),
        Unit(name="NetWorthTimeSeriesPoint", kind=Kind.VALUE_OBJECT),
        Unit(name="AccountLineageLine", kind=Kind.VALUE_OBJECT),
        Unit(
            name="EquationDiagnosticCategory",
            kind=Kind.VALUE_OBJECT,
            module="base/diagnostics.py",
        ),
        Unit(
            name="EquationDiagnosticResult",
            kind=Kind.VALUE_OBJECT,
            module="base/diagnostics.py",
        ),
        Unit(
            name="diagnose_equation_imbalance",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/diagnostics.py",
        ),
        Unit(
            name="run_balance_sheet_diagnostics",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/diagnostics.py",
        ),
        Unit(
            name="compute_personal_data_quality",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/data_quality_service.py",
        ),
        Unit(name="ReportSnapshot", kind=Kind.AGGREGATE_ROOT),
        # ── extension (report generation + lanes) ──
        Unit(
            name="generate_balance_sheet",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/balance_sheet.py",
        ),
        Unit(
            name="generate_annualized_income_schedule",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/annualized_income.py",
        ),
        Unit(
            name="generate_income_statement",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/income_statement.py",
        ),
        Unit(
            name="generate_cash_flow",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/cash_flow.py",
        ),
        Unit(
            name="_aggregate_balances_sql",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/_core.py",
        ),
        Unit(
            name="_aggregate_net_income_sql",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/_core.py",
        ),
        Unit(
            name="get_net_worth_timeseries",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/net_worth.py",
        ),
        Unit(
            name="get_net_worth_allocation_schedule",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/net_worth.py",
        ),
        Unit(
            name="get_category_breakdown",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/net_worth.py",
        ),
        Unit(
            name="get_account_trend",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/net_worth.py",
        ),
        Unit(
            name="get_account_lineage",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/lineage.py",
        ),
        Unit(
            name="PackageSectionContribution",
            kind=Kind.VALUE_OBJECT,
            module="base/package_contribution.py",
        ),
        Unit(
            name="PackageCashInputs",
            kind=Kind.VALUE_OBJECT,
            module="base/package_contribution.py",
        ),
        Unit(
            name="personal_report_package_target",
            kind=Kind.FACTORY,
            module="base/package_decision.py",
        ),
        Unit(
            name="personal_report_package_decision_ref",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/package_document.py",
        ),
        Unit(
            name="ReportingReadRepository",
            kind=Kind.REPOSITORY,
        ),
        # ── data (projection / sink declarations) ──
        Unit(name="ReportSnapshotProjection", kind=Kind.PROJECTION),
        Unit(name="ReportTraceabilityProjection", kind=Kind.PROJECTION),
        Unit(name="AccountLineageTreeProjection", kind=Kind.PROJECTION),
        Unit(name="FrameworkPolicyDecisionProjection", kind=Kind.PROJECTION),
    ],
    implementations={"be": "apps/backend/src/reporting", "fe": None},
    interface=[
        "MAX_NET_WORTH_DAILY_POINTS",
        "PERSONAL_REPORT_PACKAGE_CONTRACT",
        "PERSONAL_REPORT_PACKAGE_NOTES",
        "PackageAssembler",
        "PackageSectionContribution",
        "personal_report_package_target",
        "personal_report_package_decision_ref",
        "PackageDocumentVersionError",
        "EquationDiagnosticCategory",
        "EquationDiagnosticResult",
        "diagnose_equation_imbalance",
        "run_balance_sheet_diagnostics",
        "current_package_document_summary",
        "AnnualizedIncomeTotals",
        "CashFlowItem",
        "CashFlowResponse",
        "CashFlowSummary",
        "compute_personal_data_quality",
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
        # Composition-root injection ports (#1666/#1610): main.py and the
        # backend test conftest wire the app-remainder FX service and the
        # manual-valuation lines builder through these.
        "register_fx_gateway",
        "register_manual_valuation_lines_provider",
        "resolve_line_currency",
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
            id="snapshot-orm-owner",
            statement=(
                "ReportSnapshot and ReportType are reporting-owned ORM vocabulary "
                "and register exactly once on shared SQLAlchemy metadata."
            ),
            test=(
                "tests/tooling/test_s3_pr_d_structure.py"
                "::test_AC_reporting_snapshot_ownership_and_metadata_registration"
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
        ac('AC-reporting.fx-port.1', "Reporting's FX gateway exposes exact rate, conversion, and prefetch protocols without Callable[..., Any] or variadic Any forwarders.", 'tests/tooling/test_s3_pr_d_structure.py::test_AC_s3_typed_fx_ports_have_no_erased_registration_or_forwarders'),
        ac('AC-reporting.snapshot-ownership.1', 'ReportSnapshot and ReportType are published and mapped by reporting; extraction defines and exports neither.', 'tests/tooling/test_s3_pr_d_structure.py::test_AC_reporting_snapshot_ownership_and_metadata_registration'),
        ac('AC-reporting.vocabulary-ownership.1', 'PersonalReportingFrameworkId, ReportLineId, and PolicyDimension are reporting-owned base value objects; the delivery schema may only re-export those exact definitions.', 'tests/tooling/test_vocabulary_ownership.py::test_AC_reporting_vocabulary_ownership_1_reporting_owns_wire_enums', priority='P1'),
        ac('AC-reporting.single-owner.1', 'Manual-valuation line naming is defined only by pricing, its fact owner; reporting contains no dead duplicate helper that can drift independently.', 'apps/backend/tests/reporting/test_reporting_calc_extraction.py::test_AC_reporting_single_owner_1_has_no_valuation_line_name_copy', priority='P1'),
        # ── opening-balance confidence-tier gate (was EPIC-002 AC2.16.4 —
        # EPIC-002 never owned this behavior; it's report assembly, not
        # double-entry posting) ──
        ac('AC-reporting.opening-balance.1', 'A balance sheet with posted activity but no recorded opening balance emits an opening_balance_warnings entry (type=missing_opening_balance), and the package assembler treats it as a deterministic blocker.', 'apps/backend/tests/reporting/test_balance_sheet_opening_balance_gate.py::test_AC2_16_4_balance_sheet_warns_when_opening_balance_missing', priority='P1'),
        ac('AC-reporting.opening-balance.2', "Once an opening-balance entry is posted for the account that triggered the degrade, the balance sheet's opening_balance_warnings clears to empty on the next generation.", 'apps/backend/tests/reporting/test_balance_sheet_opening_balance_gate.py::test_AC2_16_4_balance_sheet_clears_warning_once_opening_balance_recorded', priority='P1'),
        ac('AC-reporting.opening-balance.3', 'The net-worth allocation schedule surfaces the same opening_balance_warnings as the balance sheet when the user needs an opening balance.', 'apps/backend/tests/reporting/test_balance_sheet_opening_balance_gate.py::test_AC2_16_4_net_worth_allocation_surfaces_opening_balance_warning', priority='P1'),
        # ── EPIC-020 framework-aware personal reporting (US-GAAP-like /
        # HK-FRS-like), all proof_kind in {exact, property}: both valid under
        # a CODE-ONLY tier, so this roadmap is tier-flip-ready once EPIC-005's
        # larger AC set (still pending) is assessed the same way ──
        ac('AC-reporting.framework.1', 'The framework registry SSOT and EPIC-020 define `personal_us_gaap_like` and `personal_hkfrs_like`, exclude a CN/CAS v1 framework, and state that outputs are personal management reports rather than statutory filings.', 'tests/tooling/test_framework_reporting_epic_contract.py::test_AC20_1_1_framework_registry_defines_us_hk_personal_targets', proof_kind='exact'),
        ac('AC-reporting.lanes.1', 'The framework-reporting SSOT and EPIC-020 declare the six-lane fact-forward/target-backward architecture (source capture, evidence control, canonical ledger, portfolio subledger, framework policy, report assembly) as mutually exclusive and collectively covering, with distinct lane owners.', 'tests/tooling/test_framework_reporting_epic_contract.py::test_AC20_2_1_mece_direction_matrix_declares_distinct_owner_lanes', proof_kind='exact'),
        ac('AC-reporting.target.1', 'The framework target package contract works backward from report outputs: it enumerates required statements and schedules, report line mappings, policy dimensions, evidence anchors, disclosure requirements, and blocker conditions before report assembly runs.', 'tests/tooling/test_framework_reporting_epic_contract.py::test_AC20_3_1_framework_target_contract_is_report_output_backward', proof_kind='exact'),
        ac('AC-reporting.policy.1', 'The v1 policy matrix covers cash and bank accounts, listed equities/ETFs, funds and money-market products, dividends and interest, brokerage fees, FX, RSU/ESOP/options, and property/mortgage/private-manual assets, each across recognition, measurement, classification, presentation, and disclosure.', 'tests/tooling/test_framework_reporting_epic_contract.py::test_AC20_4_1_policy_matrix_covers_personal_finance_domains', proof_kind='exact'),
        ac('AC-reporting.policy.2', 'The framework policy layer is read-only: it consumes canonical ledger, portfolio facts, and evidence readiness against the selected framework target without mutating source records, journal entries, portfolio lots, market data, or report snapshots, and it does not itself parse settlements.', 'tests/tooling/test_framework_reporting_epic_contract.py::test_AC20_5_1_policy_layer_is_read_only_between_facts_and_report', proof_kind='exact'),
        ac('AC-reporting.ai.1', 'An AI measurement/disclosure suggestion affects trusted output only after becoming a structured field carrying a source anchor, confidence tier, review state, policy field name, and accepted value; unreviewed AI suggestions and incomplete policy fields surface as readiness blocker codes, and the report package UI requires an explicit framework selection before loading framework-scoped output.', 'tests/tooling/test_framework_reporting_epic_contract.py::test_AC20_6_1_ai_suggestions_require_structured_reviewed_policy_fields', proof_kind='exact'),
        ac('AC-reporting.framework.2', 'The same settlement-and-portfolio fixture drives both US-like and HK-like personal report packages, producing framework-specific line mappings, notes bases, source anchors, export metadata, and readiness blockers from a single input set.', 'apps/backend/tests/reporting/test_framework_policy.py::test_AC20_7_1_same_settlement_fixture_drives_us_hk_report_policy_outputs', proof_kind='exact'),
        ac('AC-reporting.pipeline.1', 'Every L2 category — each `AssetType` and each `ManualValuationComponentType` — resolves to a concrete L1 report line via the framework policy matrix in both `personal_us_gaap_like` and `personal_hkfrs_like`; a known category landing in the UNSUPPORTED/gap path fails the gate (BOND/OTHER regression covered), so report assembly never improvises a line for a known category.', 'apps/backend/tests/reporting/test_framework_policy_coverage.py::test_AC20_8_1_every_asset_type_maps_to_an_l1_line', proof_kind='property'),
        ac('AC-reporting.pipeline.2', 'EPIC-020 declares the three reporting-pipeline layers (event→L2, L2→L1, L1→report), each with a locked EPIC-026 tier and its valid proof obligation, confining LLM authority to the LLM-LED layer; L1 report assembly iterates the registered L1 lines, aggregates Decimal source lines exactly, keeps portfolio cost basis plus market adjustment on the framework securities L1 line, and fails closed rather than improvising an unmapped known source line.', 'apps/backend/tests/reporting/test_l1_registry_aggregation.py::test_AC20_9_1_framework_balance_sheet_exact_aggregation', proof_kind='property'),
        # ── DRY/SSOT simplification (EPIC-025) ──
        ac('AC-reporting.dry-ssot.1', 'Pure reporting math (money quantization, accounting sign rules, period boundaries, income-bucket classification) is provided by `services.reporting_calc` and re-used by `services.reporting`; the balance-sheet equation and report totals are unchanged.', 'apps/backend/tests/reporting/test_reporting_calc_extraction.py::test_reporting_calc_extraction', priority='P1', proof_kind='exact'),
        ac('AC-reporting.dry-ssot.2', 'Shared reporting fixtures (standard chart of accounts, golden dashboard scenario, standard FX rates) are provided by a single `tests/reporting/_report_fixtures` module and reused, with duplicate per-file `test_user_id` fixtures removed; existing AC traceability is preserved.', 'apps/backend/tests/reporting/test_report_fixtures_shared.py::test_report_fixtures_shared', priority='P1', proof_kind='exact'),
        # ── export-envelope (EPIC-006 AC6.33.5/.6/.8/.9, closeout wave 3,
        # #1416) — ExportStreamEnvelope (apps/backend/src/schemas/streaming.py)
        # is the reporting/export surface of the typed streaming contract; the
        # chat-side envelope already migrated to common/advisor/contract.py's
        # roadmap (AC-advisor.envelope.*) ──
        ac('AC-reporting.export-envelope.1', "ExportStreamEnvelope declares the wire media type and builds an attachment Content-Disposition header carrying the envelope's filename.", 'apps/backend/tests/ai/test_streaming_contract.py::test_AC6_33_5_export_envelope_builds_attachment_headers'),
        ac('AC-reporting.export-envelope.2', 'ExportStreamEnvelope rejects a media type outside the declared wire set (e.g. application/pdf) at construction.', 'apps/backend/tests/ai/test_streaming_contract.py::test_AC6_33_6_export_envelope_rejects_unknown_media_type'),
        ac('AC-reporting.export-envelope.3', "GET /reports/export's response media type and Content-Disposition header equal what ExportStreamEnvelope would produce for the same filename.", 'apps/backend/tests/reporting/test_reports_router.py::test_AC6_33_8_export_response_matches_typed_envelope'),
        ac('AC-reporting.export-envelope.4', 'ExportStreamEnvelope rejects a filename carrying CR/LF, a double-quote, a semicolon, or a path separator, since the filename is interpolated into the Content-Disposition header and each of those characters would break out of it or inject a header.', 'apps/backend/tests/ai/test_streaming_contract.py::test_AC6_33_9_export_envelope_rejects_unsafe_filename'),
        # ── group balance-sheet: balance-sheet generation (was EPIC-005
        # AC5.1.1-4, migration closeout continuation, #1663 / #1716) ──
        ac('AC-reporting.balance-sheet.1', 'The generated balance sheet satisfies the accounting equation: assets = liabilities + equity (net income included).', 'apps/backend/tests/reporting/test_reporting.py::test_balance_sheet_equation'),
        ac('AC-reporting.balance-sheet.2', 'FX unrealized gain is calculated for foreign-currency balances on the balance sheet.', 'apps/backend/tests/reporting/test_reporting_fx.py::test_fx_unrealized_gain_calculation'),
        ac('AC-reporting.balance-sheet.3', 'Multi-currency account balances aggregate into the base reporting currency on the balance sheet.', 'apps/backend/tests/reporting/test_reporting_fx.py::test_multi_currency_aggregation'),
        ac('AC-reporting.balance-sheet.4', 'GET /reports/balance-sheet returns the generated balance sheet payload.', 'apps/backend/tests/reporting/test_reports_router.py::test_balance_sheet_endpoint'),
        ac('AC-reporting.balance-sheet.5', "A historical as_of_date balance sheet excludes a portfolio position whose ManagedPosition.acquisition_date postdates that as_of_date (consistent with portfolio's documented point-in-time holdings rule: future snapshots are never used); the same position appears once as_of_date reaches its acquisition_date.", 'tests/e2e/test_personal_financial_report_package.py::test_personal_financial_report_package_post_merge_journey', priority='P1', proof_kind='property'),
        ac('AC-reporting.balance-sheet.6', "A manual valuation component recorded only after the report's as_of_date stays out of the balance-sheet totals AND is disclosed in the response's portfolio_warnings, so a historical balance sheet never silently reads as complete (#1796).", 'apps/backend/tests/reporting/test_reporting_net_worth_components.py::test_AC_reporting_balance_sheet_6_valuation_gap_disclosed_in_portfolio_warnings', priority='P1'),
        ac('AC-reporting.balance-sheet.7', 'Balance sheet equation evaluation does not use circular plugging for CTA, correctly reports is_balanced=False when assets are corrupted or dropped, and excludes FX_REVALUATION entries from SQL aggregate balances to prevent double-counting.', 'apps/backend/tests/reporting/test_falsifiable_balance_sheet.py::test_balance_sheet_cta_and_aggregation_falsifiability', priority='P1'),
        # ── group income-statement (was EPIC-005 AC5.2.1-3, migration
        # closeout continuation, #1663 / #1716) ──
        ac('AC-reporting.income-statement.1', 'The income statement computes net income as income minus expenses.', 'apps/backend/tests/reporting/test_reporting.py::test_income_statement_calculation'),
        ac('AC-reporting.income-statement.2', 'The income statement includes comprehensive income from FX effects.', 'apps/backend/tests/reporting/test_reporting_fx.py::test_income_statement_comprehensive_income', priority='P1'),
        ac('AC-reporting.income-statement.3', 'The income statement rejects an invalid date range (start after end) with a domain error.', 'apps/backend/tests/reporting/test_reporting.py::test_income_statement_invalid_range', priority='P1'),
        # ── group cash-flow: cash-flow statement + trend/breakdown endpoints
        # (was EPIC-005 AC5.3.1-5, migration closeout continuation,
        # #1663 / #1716) ──
        ac('AC-reporting.cash-flow.1', 'The cash-flow statement is generated with operating, investing, and financing sections.', 'apps/backend/tests/reporting/test_reporting.py::test_cash_flow_statement'),
        ac('AC-reporting.cash-flow.2', 'A period with no cash movement generates an empty (zeroed) cash-flow statement, not an error.', 'apps/backend/tests/reporting/test_reporting.py::test_cash_flow_empty_period', priority='P1'),
        ac('AC-reporting.cash-flow.3', 'GET /reports/trend returns account trend data across different period granularities.', 'apps/backend/tests/api/test_reports_router.py::test_account_trend_with_period', priority='P1'),
        ac('AC-reporting.cash-flow.4', 'GET /reports/breakdown returns the category breakdown.', 'apps/backend/tests/api/test_reports_router.py::test_category_breakdown_success', priority='P1'),
        ac('AC-reporting.cash-flow.5', 'GET /reports/breakdown honors the requested period parameter.', 'apps/backend/tests/api/test_reports_router.py::test_category_breakdown_with_period', priority='P1'),
        # ── group fx: multi-currency conversion fallbacks (was EPIC-005
        # AC5.4.1-4, migration closeout continuation, #1663 / #1716) ──
        ac('AC-reporting.fx.1', 'Report FX conversion falls back through the documented rate-resolution chain.', 'apps/backend/tests/reporting/test_reporting_fx.py::test_reporting_fx_fallbacks', priority='P1'),
        ac('AC-reporting.fx.2', 'Balance-sheet net income uses the FX fallback path when a direct rate is missing.', 'apps/backend/tests/reporting/test_reporting_fx.py::test_balance_sheet_net_income_fx_fallback', priority='P1'),
        ac('AC-reporting.fx.3', 'Reports lazily resolve a missing cross rate (e.g. HKD/SGD) from stored bridge rates.', 'apps/backend/tests/reporting/test_reporting_fx.py::test_reports_lazy_resolve_missing_hkd_sgd_from_bridge_rates'),
        ac('AC-reporting.fx.4', 'Missing report FX rates produce explicit partial warnings for the unconvertible currency instead of aborting the whole aggregation.', 'apps/backend/tests/reporting/test_reporting_fx_fallbacks.py::test_aggregate_balances_missing_fx_skips_unconvertible_currency_with_warning'),
        # ── group errors: report error handling + auth boundary (was EPIC-005
        # AC5.5.1-5, migration closeout continuation, #1663 / #1716) ──
        ac('AC-reporting.errors.1', 'Report-generation failures surface as structured router errors.', 'apps/backend/tests/reporting/test_reports_errors.py::test_reports_router_errors_extended', priority='P1'),
        ac('AC-reporting.errors.2', 'Each reports endpoint maps a ReportError to a structured HTTP error response (TestReportsRouterErrors suite; representative test cited).', 'apps/backend/tests/reporting/test_reports_router_errors.py::test_balance_sheet_report_error', priority='P1'),
        ac('AC-reporting.errors.3', 'Unauthenticated clients cannot access the reports endpoints.', 'apps/backend/tests/api/test_reports_router.py::test_unauthenticated_access', priority='P1'),
        ac('AC-reporting.errors.4', 'The reports router endpoints respond successfully for an authenticated user (representative endpoint test cited).', 'apps/backend/tests/reporting/test_reports_router.py::test_income_statement_endpoint', priority='P1'),
        ac('AC-reporting.errors.5', "GET /reports/{report_type}/snapshots returns the user's persisted report snapshots.", 'apps/backend/tests/api/test_reports_router.py::test_list_report_snapshots_returns_created_snapshots', priority='P1'),
        # ── group kpis: dashboard/report KPI surfaces + FX guardrails (was
        # EPIC-005 AC5.6.4-5 and AC5.6.7-11 — AC5.6.4's frontend dashboard-card
        # half stays in EPIC-005; migration closeout continuation,
        # #1663 / #1716) ──
        ac('AC-reporting.kpis.1', 'The annualized income KPI endpoint groups the last 12 months of income; calculation ownership stays with AC11.8.1.', 'apps/backend/tests/reporting/test_income_annualized_router.py::test_annualized_income_endpoint_groups_last_12_month_income'),
        ac('AC-reporting.kpis.2', 'Unrealized P&L is reflected in balance-sheet equity (golden dashboard fixture asserts exact totals).', 'apps/backend/tests/reporting/test_reporting.py::test_reporting_dashboard_fixture_exact_totals'),
        ac('AC-reporting.kpis.3', 'Report output lists the currencies that used the average-rate spot fallback.', 'apps/backend/tests/reporting/test_reporting_fx_revaluation_integration.py::test_income_statement_includes_average_rate_fallback_warning', priority='P1'),
        ac('AC-reporting.kpis.4', 'Account trend raises when a prefetched non-base FX rate is missing.', 'apps/backend/tests/reporting/test_reporting_extreme_fallbacks.py::test_account_trend_raises_when_prefetched_rate_missing', priority='P1'),
        ac('AC-reporting.kpis.5', 'Category breakdown raises when a prefetched non-base FX rate is missing.', 'apps/backend/tests/reporting/test_reporting_extreme_fallbacks.py::test_category_breakdown_raises_when_prefetched_rate_missing', priority='P1'),
        ac('AC-reporting.kpis.6', 'Cash flow raises when the start-date non-base FX rate is missing.', 'apps/backend/tests/reporting/test_reporting_extreme_fallbacks.py::test_cash_flow_raises_when_start_date_rate_missing', priority='P1'),
        ac('AC-reporting.kpis.7', 'Cash flow raises when the end-date FX rate is missing, propagating FxRateError.', 'apps/backend/tests/reporting/test_reporting_extreme_fallbacks.py::test_cash_flow_raises_when_end_date_rate_missing', priority='P1'),
        # ── group package-investment: investment-performance section consumption
        # (was EPIC-005 AC5.8.1's backend contract half — the frontend render
        # and post-merge journey proofs stay in EPIC-005; migration closeout
        # continuation, #1663 / #1716) ──
        ac('AC-reporting.package-investment.1', 'The personal report package defines the investment_performance section as a consumer of the EPIC-017 schedule API, preserving source_links and notes.', 'tests/tooling/test_investment_performance_report_contract.py::test_AC5_8_1_personal_report_package_consumes_investment_schedule_contract'),
        # ── group package-contract: personal report package API contract (was
        # EPIC-005 AC5.9.1-2 — the frontend rows AC5.9.3-4 stay in EPIC-005;
        # migration closeout continuation, #1663 / #1716) ──
        ac('AC-reporting.package-contract.1', 'The document-embedded package contract defines the required section IDs, labels, owners, and source semantics.', 'apps/backend/tests/api/test_personal_report_package_contract.py::test_AC5_9_1_package_contract_defines_required_sections'),
        ac('AC-reporting.package-contract.2', 'The package contract exposes Decimal-safe total fields and explicit period/as-of semantics.', 'apps/backend/tests/api/test_personal_report_package_contract.py::test_AC5_9_2_package_contract_marks_decimal_totals_and_period_semantics'),
        # ── group logic-audit: financial statement logic audit fixes (was
        # EPIC-005 AC5.10.1-2, migration closeout continuation,
        # #1663 / #1716) ──
        ac('AC-reporting.logic-audit.1', 'Cash-flow beginning cash, ending cash, and net cash flow use cumulative cash balances.', 'apps/backend/tests/reporting/test_financial_logic_audit.py::test_AC5_10_1_cash_flow_uses_cumulative_cash_balances'),
        ac('AC-reporting.logic-audit.2', 'Cash-flow operating, investing, and financing totals preserve inflow/outflow signs.', 'apps/backend/tests/reporting/test_financial_logic_audit.py::test_AC5_10_2_cash_flow_activity_totals_preserve_signs'),
        # ── group package-annualized: annualized income schedule consumption
        # (was EPIC-005 AC5.11.1 and AC5.11.3 — the frontend row AC5.11.2 stays
        # in EPIC-005; migration closeout continuation, #1663 / #1716) ──
        ac('AC-reporting.package-annualized.1', 'The package contract requires the typed annualized_income_long_term section inside PersonalReportPackageDocument.', 'apps/backend/tests/api/test_personal_report_package_contract.py::test_AC5_11_1_package_contract_marks_annualized_schedule_ready'),
        ac('AC-reporting.package-annualized.2', 'The annualized income package schedule converts mixed-currency income and restricted totals into one reporting currency.', 'apps/backend/tests/reporting/test_annualized_income_schedule.py::test_AC5_11_3_AC11_11_3_annualized_schedule_converts_mixed_currency_totals'),
        # ── group package-notes: notes and disclosure basis (was EPIC-005
        # AC5.12.1-2 and AC5.12.4 — the frontend row AC5.12.3 stays in
        # EPIC-005; migration closeout continuation, #1663 / #1716) ──
        ac('AC-reporting.package-notes.1', 'The package notes endpoint returns the required note IDs, owner EPICs, source states, and non-compliance wording.', 'apps/backend/tests/api/test_personal_report_package_contract.py::test_AC5_12_1_package_notes_endpoint_returns_required_note_taxonomy'),
        ac('AC-reporting.package-notes.2', 'The package contract marks notes ready and points at the notes endpoint.', 'apps/backend/tests/api/test_personal_report_package_contract.py::test_AC5_12_2_package_contract_marks_notes_ready'),
        ac('AC-reporting.package-notes.3', 'The post-merge package proof asserts the notes endpoint, required note IDs, and non-compliance wording.', 'tests/e2e/test_personal_financial_report_package.py::test_personal_financial_report_package_post_merge_journey'),
        # ── group package-traceability: source-ledger-report appendix (was
        # EPIC-005 AC5.13.1-2 and AC5.13.4-5 — the frontend row AC5.13.3 stays
        # in EPIC-005; migration closeout continuation, #1663 / #1716) ──
        ac('AC-reporting.package-traceability.1', 'The package traceability endpoint returns source-to-ledger anchors per report line.', 'apps/backend/tests/api/test_personal_report_package_contract.py::test_AC5_13_1_package_traceability_endpoint_returns_section_line_anchors'),
        ac('AC-reporting.package-traceability.2', 'The traceability appendix exposes explicit completeness states where anchors are unavailable.', 'apps/backend/tests/api/test_personal_report_package_contract.py::test_AC5_13_2_package_traceability_declares_completeness_warnings'),
        ac('AC-reporting.package-traceability.3', 'The post-merge package proof fails trusted totals without source/ledger anchors or explicit manual inputs.', 'tests/e2e/test_personal_financial_report_package.py::test_personal_financial_report_package_post_merge_journey'),
        ac('AC-reporting.package-traceability.4', 'The package traceability endpoint returns current-user dynamic source identifiers and excludes unrelated-user anchors.', 'apps/backend/tests/api/test_personal_report_package_contract.py::test_AC5_13_5_package_traceability_returns_dynamic_current_user_identifiers'),
        # ── group integration: backend reporting integration journey (was
        # EPIC-005 AC5.15.1, migration closeout continuation,
        # #1663 / #1716) ──
        ac('AC-reporting.integration.1', 'Multi-currency posted entries generate balanced balance-sheet, income-statement, and cash-flow reports in the base currency.', 'apps/backend/tests/integration/test_reporting_e2e.py::test_AC5_15_1_multicurrency_reporting_cycle_reconciles_bs_is_cf'),
        # ── group trust-signals: report trust signals + restricted-asset
        # defaults (was EPIC-005 AC5.16.1-2 backend halves and AC5.16.4 — the
        # frontend halves and AC5.16.3 stay in EPIC-005; migration closeout
        # continuation, #1663 / #1716) ──
        ac('AC-reporting.trust-signals.1', 'The balance sheet defaults restricted holdings to excluded and exposes an include toggle.', 'apps/backend/tests/reporting/test_reports_router.py::test_AC5_16_1_balance_sheet_defaults_to_excluding_restricted_holdings'),
        ac('AC-reporting.trust-signals.2', 'Report responses preserve backend fx_warnings so pages never silently render partial totals.', 'apps/backend/tests/reporting/test_reports_router.py::test_AC5_16_2_cash_flow_response_preserves_fx_warnings'),
        ac('AC-reporting.trust-signals.3', 'Package traceability lines expose source classes, proof level, anchor count, and blocker codes for report-line confidence review.', 'apps/backend/tests/api/test_personal_report_package_contract.py::test_AC5_13_1_package_traceability_endpoint_returns_section_line_anchors'),
        # ── group csv-export: authenticated report CSV exports (was EPIC-005
        # AC5.17.1's backend half — the frontend apiDownload half and AC5.17.2
        # stay in EPIC-005; migration closeout continuation, #1663 / #1716) ──
        ac('AC-reporting.csv-export.1', 'The backend CSV export supports cash-flow reports with date-range and currency filters.', 'apps/backend/tests/reporting/test_reports_router.py::test_AC5_17_1_cash_flow_export_returns_csv'),
        # ── group package-snapshot: durable package snapshot artifact (was
        # EPIC-005 AC5.19.1-3 — the frontend row AC5.19.4 stays in EPIC-005;
        # migration closeout continuation, #1663 / #1716) ──
        ac('AC-reporting.package-snapshot.1', 'POST /api/reports/package/generate creates an immutable package snapshot; blocked readiness may generate only a draft while ready readiness generates trusted output.', 'apps/backend/tests/api/test_personal_report_package_contract.py::test_AC5_19_1_package_generate_creates_draft_or_trusted_snapshot'),
        ac('AC-reporting.package-snapshot.2', 'Package snapshot list/reopen endpoints are user-scoped and reopening returns the original payload after live inputs change.', 'apps/backend/tests/api/test_personal_report_package_contract.py::test_AC5_19_2_package_snapshot_get_is_user_scoped_and_immutable'),
        ac('AC-reporting.package-snapshot.3', 'Package JSON and CSV downloads are derived from a saved snapshot rather than recalculating live data.', 'apps/backend/tests/api/test_personal_report_package_contract.py::test_AC_reporting_package_document_4_exports_the_selected_frozen_document'),
        # ── group package-document: one typed delivery artifact (#567) ──
        ac('AC-reporting.package-document.1', 'The personal report package is a versioned, Decimal-safe document with required typed balance-sheet, income-statement, cash-flow, investment, annualized-income, notes, traceability, and immutable input-manifest sections.', 'apps/backend/tests/reporting/test_package_document.py::test_AC_reporting_package_document_1_requires_typed_delivery_sections', proof_kind='exact'),
        ac('AC-reporting.package-document.2', 'Preview, generation, persistence, reopen, and export use the one PackageAssembler document path; the reports router cannot retain a private section aggregator or live package export branch.', 'apps/backend/tests/reporting/test_package_document.py::test_AC_reporting_package_document_2_has_one_assembler_and_no_live_package_export', proof_kind='exact'),
        ac('AC-reporting.package-document.3', 'Trusted/final package state is the projection of one persisted CODE-ONLY TraceRecord MANIFEST decision over the exact current contributing decisions and deterministic section observation; missing, stale, legacy, or superseded inputs produce draft/blocked output and no trusted decision.', 'apps/backend/tests/reporting/test_package_document.py::test_AC_reporting_package_document_3_trust_is_one_trace_decision_fold', proof_kind='exact'),
        ac('AC-reporting.package-document.4', 'A selected frozen document is the only JSON/CSV export input; a live-data mutation after generation cannot change the exported identity, totals, traceability, or typed section payloads.', 'apps/backend/tests/api/test_personal_report_package_contract.py::test_AC_reporting_package_document_4_exports_the_selected_frozen_document', proof_kind='property'),
        ac('AC-reporting.package-document.5', 'Package decision emission and frozen snapshot persistence share the caller-owned transaction, so a failure after trace flush leaves neither TraceRecord nor snapshot.', 'apps/backend/tests/reporting/test_package_document.py::test_AC_reporting_package_document_5_trace_and_snapshot_rollback_together', proof_kind='exact'),
        ac('AC-reporting.package-document.6', 'A whole-production-tree certificate permits one PackageDocument producer, forbids consumer-owned readiness/trust calculations and live selected-snapshot reads, and requires reports, statements, workflow, advisor, and frontend package surfaces to consume the same document or its typed projection.', 'apps/backend/tests/reporting/test_package_document.py::test_AC_reporting_package_document_6_producer_and_consumer_closure', proof_kind='exact'),
        ac('AC-reporting.package-document.7', 'PackageAssembler adapts extraction, ledger, and pricing inputs into one typed PackageSectionContribution shape and folds only those exact decision/input refs into the manifest. The traceability appendix renders the same contribution set; raw foreign-package rows and display labels cannot authorize a package.', 'apps/backend/tests/reporting/test_package_document.py::test_AC_reporting_package_document_7_manifest_folds_only_typed_contributions', proof_kind='exact'),
        ac('AC-reporting.package-document.8', 'The PackageDocument cash-flow section receives an exact typed set of cash-balance account identities from authoritative bank-statement contributions. Account names cannot classify package cash, and missing or ambiguous cash inputs block trusted output.', 'apps/backend/tests/reporting/test_financial_logic_audit.py::test_AC_reporting_package_document_8_uses_exact_cash_inputs_not_account_names', proof_kind='exact'),
        ac('AC-reporting.package-document.9', 'Every authoritative PackageSectionContribution carries one typed audit decision reference containing its exact target and assertion. Package assembly accepts the contribution only when the current tenant projection matches all three coordinates; missing, cross-scope, stale, target-mismatched, or assertion-mismatched decisions remain unproven.', 'apps/backend/tests/reporting/test_package_document.py::test_AC_reporting_package_document_9_requires_exact_decision_coordinates', proof_kind='exact'),
        ac('AC-reporting.package-document.10', 'Reporting publishes one pure package-decision coordinate builder over the exact frozen document semantics, and PackageAssembler consumes that same builder. A consumer can reconstruct the persisted decision target and assertion from the selected frozen document; changing any bound document field changes the target version, so an opaque decision id alone cannot authorize the package.', 'apps/backend/tests/reporting/test_package_document.py::test_AC_reporting_package_document_10_reconstructs_exact_decision_coordinates', proof_kind='exact'),
        ac('AC-reporting.package-document.11', "Package readiness validates cumulative balance-sheet and selected-period income against matching ledger periods. Prior-period activity does not block a valid monthly package; inconsistent section values remain blocked and saved exports retain the selected document's period-specific values.", 'apps/backend/tests/reporting/test_package_period_readiness.py::test_AC_reporting_package_document_11_prior_period_package_lifecycle', priority='P1', proof_kind='exact'),
        ac('AC-reporting.package-document.12', "The package page accepts an explicit reporting start and end date. Preview and generation submit that exact period with as_of_date equal to the selected end; empty or reversed dates fail locally without a request. Reopening and exporting a saved package retain the selected frozen artifact's period and identity.", 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC-reporting.package-document.12 previews and generates the selected month through the page', proof_kind='exact'),
        # ── group year-scale: year-scale reporting validation (was EPIC-005
        # AC5.20.1, migration closeout continuation, #1663 / #1716) ──
        ac('AC-reporting.year-scale.1', "At a full year's transaction volume the three statements tie out and generate within a wall-clock backstop, guarding against a silent O(n^2) regression.", 'apps/backend/tests/reporting/test_year_scale_reporting.py::test_AC5_20_year_scale_reporting_ties_out_within_budget', priority='P1'),
        # ── group income-typed: income module typed currency + typed
        # intermediates (was EPIC-005 AC5.32.1-6, migration closeout
        # continuation, #1663 / #1716) ──
        ac('AC-reporting.income-typed.1', 'AnnualizedIncomeResponse.currency is the shared typed CurrencyCode (validated length + normalized), not a soft str.', 'apps/backend/tests/reporting/test_income_typed_currency.py::test_AC5_32_1_currency_code_type_validates_and_normalizes', priority='P2'),
        ac('AC-reporting.income-typed.2', 'Income totals accumulate in a typed AnnualizedIncomeTotals Decimal intermediate, not a string-keyed dict.', 'apps/backend/tests/reporting/test_income_typed_currency.py::test_AC5_32_2_annualized_income_totals_is_typed_intermediate', priority='P2'),
        ac('AC-reporting.income-typed.3', 'resolve_line_currency centralizes the line/account/base currency fallback + normalization.', 'apps/backend/tests/reporting/test_income_typed_currency.py::test_AC5_32_3_resolve_line_currency_uses_canonical_fallback_chain', priority='P2'),
        ac('AC-reporting.income-typed.4', 'An explicit FX-failure response model (FxConversionErrorResponse) is declared for the income endpoint.', 'apps/backend/tests/reporting/test_income_typed_currency.py::test_AC5_32_4_fx_conversion_error_response_model_declared', priority='P2'),
        ac('AC-reporting.income-typed.5', 'Currency normalization is a single shared helper (normalize_currency_code), not duplicated strip/upper.', 'apps/backend/tests/reporting/test_income_typed_currency.py::test_AC5_32_5_normalize_currency_code_is_shared_helper', priority='P2'),
        ac('AC-reporting.income-typed.6', 'The income endpoint normalizes a soft (lower-case) base-currency setting in its response.', 'apps/backend/tests/reporting/test_income_typed_currency.py::test_AC5_32_6_endpoint_returns_normalized_currency_for_soft_base_config', priority='P2'),
        # ── group snapshots-typed: report snapshots typed contract (was
        # EPIC-005 AC5.36.1-2, migration closeout continuation,
        # #1663 / #1716) ──
        ac('AC-reporting.snapshots-typed.1', 'GET /reports/{report_type}/snapshots rejects an unknown report_type with 422.', 'apps/backend/tests/api/test_typed_contract_sweep.py::test_AC5_36_1_report_snapshots_unknown_type_returns_422', priority='P2'),
        ac('AC-reporting.snapshots-typed.2', 'A valid report_type returns a typed list[ReportSnapshotSummary] response.', 'apps/backend/tests/api/test_typed_contract_sweep.py::test_AC5_36_2_report_snapshots_valid_type_returns_typed_list', priority='P2'),
        # ── group journeys: reporting core-journey E2E (was EPIC-008
        # AC8.6.1-4, migration closeout continuation, #1663 / #1716) ──
        ac('AC-reporting.journeys.1', 'The core-journey E2E views the balance sheet end to end.', 'apps/backend/tests/reporting/test_reporting_shift_left.py::test_balance_sheet_accounting_equation_articulation'),
        ac('AC-reporting.journeys.2', 'The core-journey E2E views the income statement end to end.', 'apps/backend/tests/reporting/test_reporting_shift_left.py::test_income_statement_revenues_expenses_net_income'),
        ac('AC-reporting.journeys.3', 'The core-journey E2E views the cash-flow report end to end.', 'apps/backend/tests/reporting/test_reporting_shift_left.py::test_cash_flow_bridge_reconciliation'),
        ac('AC-reporting.journeys.4', 'The core-journey E2E navigates every reports endpoint.', 'apps/backend/tests/reporting/test_reporting_shift_left.py::test_multi_period_reporting_and_cta_adjustment', priority='P1'),
        # ── group full-year: full-year statement-to-report acceptance (was
        # EPIC-008 AC8.15.1-2, migration closeout continuation,
        # #1663 / #1716) ──
        ac('AC-reporting.full-year.1', 'Multi-month CSV statements with reviewed semantic dispositions parse, approve under the balance-chain guard, auto-post without an Uncategorized fallback, and tie the assembled period reports out end to end.', 'apps/backend/tests/integration/test_full_year_statement_to_report_e2e.py::test_AC8_15_1_full_year_statement_to_report_ties_out'),
        ac('AC-reporting.full-year.2', 'A high-confidence balance-validated bank statement with no pre-selected account auto-creates+links its asset account, reaches APPROVED, and auto-posts to the ledger only after a reviewed semantic disposition supplies its counter-account.', 'apps/backend/tests/integration/test_bank_statement_auto_account_post.py::test_AC8_15_2_bank_statement_auto_creates_account_and_posts_with_reviewed_disposition', priority='P1'),
        # ── group augmentation: augmentation-layer report integrity (was
        # EPIC-008 AC8.16.1-2, migration closeout continuation,
        # #1663 / #1716) ──
        ac('AC-reporting.augmentation.1', 'A source-labelled ledger input and a superseded manual valuation both reach the report correctly: the equation holds, source confidence is not presented as assurance, and the superseded valuation is excluded.', 'apps/backend/tests/integration/test_augmentation_seam_e2e.py::test_AC8_16_1_augmentation_seam_excludes_superseded_without_source_assurance', priority='P1'),
        ac('AC-reporting.augmentation.2', "A report aggregates only the requesting user's facts: another user's accounts never appear and never inflate a total.", 'apps/backend/tests/integration/test_cross_user_report_isolation_e2e.py::test_AC8_16_2_reports_exclude_other_users_entries', priority='P1'),
        # ── group net-worth-components: retirement/benefit assets in reports
        # (was EPIC-011 AC11.20.1-2 — the frontend row AC11.20.3 stays in
        # EPIC-011; migration closeout continuation, #1663 / #1716) ──
        ac('AC-reporting.net-worth-components.1', 'Retirement accounts, social-security personal balances, legacy CPF, and insurance cash value default to restricted assets and contribute to full balance-sheet assets.', 'apps/backend/tests/reporting/test_reporting_net_worth_components.py::test_AC11_20_1_retirement_and_benefit_assets_are_restricted_assets_in_balance_sheet', priority='P1'),
        ac('AC-reporting.net-worth-components.2', 'Net-worth allocation groups retirement and benefit balances under the retirement-and-benefit asset class.', 'apps/backend/tests/reporting/test_reporting_net_worth_components.py::test_AC11_20_2_net_worth_allocation_groups_retirement_and_benefit_assets', priority='P1'),
        # ── group layer3: Layer 3/4 read integration (was EPIC-018 AC18.4.1-2
        # and AC18.4.4 — AC18.4.3 is extraction-owned and stays; migration
        # closeout continuation, #1663 / #1716) ──
        ac('AC-reporting.layer3.1', "The income statement's classification coverage reads Layer 3 APPLIED TransactionClassification rows joined to their category accounts — the report-side read of Layer 3 classifications.", 'apps/backend/tests/reporting/test_reporting_net_worth_components.py::test_income_statement_includes_applied_classification_breakdown', priority='P1'),
        ac('AC-reporting.layer3.2', 'ReportSnapshot (Layer 4) rows are generated and queryable via the reports snapshots API.', 'apps/backend/tests/api/test_reports_router.py::test_list_report_snapshots_returns_created_snapshots', priority='P1'),
        ac('AC-reporting.layer3.3', 'Income statement payloads include the applied Layer 3 classification coverage breakdown.', 'apps/backend/tests/reporting/test_reporting_net_worth_components.py::test_income_statement_includes_applied_classification_breakdown', priority='P1'),
        # ── group source-anchors: typed package source anchors (was EPIC-019
        # AC19.10.1, migration closeout continuation, #1663 / #1716) ──
        ac('AC-reporting.source-anchors.1', 'Package traceability resolves journal source IDs to typed source anchors and blocks unknown source IDs instead of presenting them as statement transactions.', 'apps/backend/tests/api/test_personal_report_package_contract.py::test_AC19_10_1_unknown_journal_source_ids_are_not_reported_as_statement_transactions'),
        # ── group lineage: account lineage drill-down (was EPIC-022 AC22.3.3
        # and AC22.7.1's backend half — AC22.7.1's frontend drawer half stays
        # in EPIC-022; migration closeout continuation, #1663 / #1716) ──
        ac('AC-reporting.lineage.1', "GET /api/reports/account-lineage returns the user-scoped posted/reconciled journal lines contributing to an account's balance, each with a journal_line evidence anchor and Decimal-safe signed amounts.", 'apps/backend/tests/reporting/test_account_lineage.py::test_AC22_3_3_account_lineage_returns_posted_contributing_lines', priority='P1'),
        ac('AC-reporting.lineage.2', "Each cash-flow line carries its account anchor (account_id) so a cash-flow amount can drill down to the account's contributing journal lines.", 'apps/backend/tests/reporting/test_reporting.py::test_reporting_dashboard_fixture_exact_totals', priority='P1'),
        # ── group provenance: normalized report-line provenance (was EPIC-022
        # AC22.13.1's reporting share — the pricing share is
        # AC-pricing.provenance.1 and the portfolio share is
        # AC-portfolio.provenance.2; migration closeout continuation,
        # #1663 / #1716) ──
        ac('AC-reporting.provenance.1', 'Report amount lines expose the normalized provenance enum (imported/manual/derived) when the source basis is known, and stay unlabeled instead of guessing.', 'apps/backend/tests/reporting/test_reporting.py::test_AC22_13_1_report_amount_lines_expose_normalized_provenance', priority='P1'),
        # ── group net-worth-timeseries: dashboard net-worth history endpoint
        # (was EPIC-005 AC5.7.1/AC5.7.3, #1821 Wave A pending-package move) ──
        ac('AC-reporting.net-worth-timeseries.1', 'GET /api/reports/net-worth/timeseries?from=YYYY-MM-DD&to=YYYY-MM-DD&granularity=monthly|daily (plus an optional 3-letter currency parameter selecting the reporting currency) returns [{date, total_assets, total_liabilities, net_worth}].', 'apps/backend/tests/reporting/test_net_worth_timeseries.py::test_net_worth_timeseries_router', priority='P1'),
        ac('AC-reporting.net-worth-timeseries.2', 'Net worth time-series respects multi-currency: each point is converted to the base currency using the historical FX rate per the transaction-date rate rule.', 'apps/backend/tests/reporting/test_net_worth_timeseries.py::test_net_worth_timeseries_uses_historical_fx_per_point', priority='P1'),
        # ── group portfolio-valuation-gate: brokerage portfolio value gate
        # (was EPIC-008 AC8.13.18/AC8.13.19, reporting-owned per the EPIC's own
        # migration note, #1821 Wave A pending-package move) ──
        ac('AC-reporting.portfolio-valuation-gate.1', 'The brokerage portfolio gate validates market valuation adjustment lines even when unrelated asset lines lower total assets (also proven at the reporting-unit level by test_portfolio_market_adjustment_survives_unrelated_negative_asset_lines in apps/backend/tests/reporting/test_reporting_net_worth_components.py).', 'tests/e2e/test_brokerage_upload_to_portfolio_value.py::test_portfolio_valuation_gate_ignores_unrelated_negative_asset_lines'),
        ac('AC-reporting.portfolio-valuation-gate.2', 'Brokerage portfolio gate failures include holdings, valuation adjustment, non-portfolio asset, and balance-sheet diagnostics.', 'tests/e2e/test_brokerage_upload_to_portfolio_value.py::test_portfolio_valuation_gate_failure_diagnostics_are_actionable'),
        # ── group annualized-dashboard: dashboard annualized-income/restricted
        # cards (was EPIC-011 AC11.8.1/AC11.8.3/AC11.8.7, #1821 Wave A
        # pending-package move) ──
        ac('AC-reporting.annualized-dashboard.1', 'GET /api/income/annualized returns {annualized_salary, annualized_bonus, annualized_dividend, annualized_total, currency, as_of} derived from the last 12 months of Income-type journal entries.', 'apps/backend/tests/reporting/test_income_annualized_router.py::test_annualized_income_endpoint_groups_last_12_month_income', priority='P1'),
        ac('AC-reporting.annualized-dashboard.2', 'GET /api/assets/restricted returns ESOP/RSU/locked holdings with {ticker, quantity, vesting_schedule, unlock_date, fair_value}.', 'apps/backend/tests/reporting/test_income_annualized_router.py::test_restricted_assets_endpoint_returns_latest_locked_holdings', priority='P1'),
        ac('AC-reporting.annualized-dashboard.3', 'GET /api/income/annualized converts mixed-currency annualized income totals into the dashboard reporting currency before aggregation.', 'apps/backend/tests/reporting/test_income_annualized_router.py::test_AC11_8_7_annualized_income_endpoint_converts_mixed_currency_totals', priority='P1'),
        # ── group package-annualized: extends the existing group with the
        # report-package annualized-income schedule rows (was EPIC-011
        # AC11.11.1-4, #1821 Wave A pending-package move) ──
        ac('AC-reporting.package-annualized.3', 'The reporting-owned annualized section returns annualized salary, bonus, dividend, total income, currency, as-of date, and trailing-period boundaries for the personal report package.', 'apps/backend/tests/reporting/test_annualized_income_schedule.py::test_AC11_11_1_AC11_11_2_annualized_schedule_includes_income_and_restricted_treatment'),
        ac('AC-reporting.package-annualized.4', 'The schedule includes ESOP/RSU/stock-option restricted holdings with valuation basis, vesting/unlock metadata, fair value, and explicit liquid-versus-restricted net worth treatment.', 'apps/backend/tests/reporting/test_annualized_income_schedule.py::test_AC11_11_1_AC11_11_2_annualized_schedule_includes_income_and_restricted_treatment'),
        # NOTE: was AC11.11.3 ("Annualized income and restricted fair-value
        # package totals are Decimal-safe and converted to the schedule
        # reporting currency") — duplicate of the ALREADY-migrated
        # AC-reporting.package-annualized.2 ("The annualized income package
        # schedule converts mixed-currency income and restricted totals into
        # one reporting currency", was AC5.11.3), which cites the exact same
        # test (test_AC5_11_3_AC11_11_3_annualized_schedule_converts_mixed_currency_totals)
        # and whose docstring already names both AC5.11.3 and AC11.11.3. The
        # EPIC-011 row is deleted with no new roadmap entry (#1821 Wave A).
        ac('AC-reporting.package-annualized.5', "Each restricted holding's valuation_basis surfaces the snapshot's structured evidence basis enum value (or unspecified when none was captured) instead of a hardcoded source-kind literal (#706).", 'apps/backend/tests/reporting/test_annualized_income_schedule.py::test_AC11_11_4_annualized_schedule_surfaces_structured_valuation_basis'),
        # ── group net-worth-components: extends the existing group with the
        # unified allocation schedule (was EPIC-017 AC17.14.2, #1821 Wave A
        # pending-package move) ──
        ac('AC-reporting.net-worth-components.3', 'Reports expose a net-worth allocation schedule grouped by asset class, liquidity class, and source currency, with signed rows that reconcile to net worth and retain source-line drill-through metadata (endpoint contract also proven by test_AC17_14_2_net_worth_allocation_endpoint_returns_contract in apps/backend/tests/reporting/test_reports_router.py).', 'apps/backend/tests/reporting/test_reporting_net_worth_components.py::test_AC17_14_2_net_worth_allocation_groups_balance_sheet_sources', priority='P1'),
        # ── group api-vectors: backend-owned API response conformance
        # vectors (#1827 G-contract-reddens, pattern from #1167). The wire
        # shape of GET /api/reports/balance-sheet is committed as
        # common/reporting/conformance/vectors.json; the backend drift test
        # recomputes it and the frontend loads the same file as mock data. ──
        ac('AC-reporting.api-vectors.1', 'The serialized GET /api/reports/balance-sheet response (BalanceSheetResponse wire shape, decimal-string amounts, real fx-warning keys) recomputed from fixed deterministic inputs equals the committed common/reporting/conformance/vectors.json, so a serializer change without vector regeneration reds CI (#1827).', 'apps/backend/tests/schemas/test_api_response_vectors.py::test_AC_reporting_api_vectors_1_balance_sheet_matches_committed_vector', priority='P1'),
        ac('AC-reporting.api-vectors.2', 'The frontend balance-sheet page test consumes the committed reporting conformance vector verbatim as its mock data (via the shared fixture helper), so a regenerated breaking wire shape reds the frontend suite (#1827).', 'apps/frontend/src/__tests__/balanceSheetPage.test.tsx::AC16.14.2 / test_AC8_13_48 renders string totals and refetches by date', priority='P1'),
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-016
        # (two-stage-review-ui) ──
        ac('AC-reporting.fe-report-surfaces.1', 'Dashboard page shows loading state before API responses resolve', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC16.12.1 shows loading state before dashboard data resolves', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.2', 'Dashboard page renders error fallback and retry action when API request fails', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC16.12.2 renders error fallback and retry action on failure', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.3', 'Dashboard page renders KPI, charts, and recent activity when API requests succeed', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC16.12.3 AC22.1.2 renders KPI, chart, activity, and alert sections when API succeeds', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.4', 'Dashboard page renders empty-state copy when trend or activity datasets are empty', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC16.12.4 renders empty-state messages for missing datasets', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.5', 'Dashboard page renders first-time onboarding when accounts, statements, or posted review output are missing', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC22.16.1 AC16.12.17 AC16.12.18 renders first-time onboarding with everyday-surface links only', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.6', 'Dashboard onboarding links users to Accounts, Statements upload, and Review in one click', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC22.16.1 AC16.12.17 AC16.12.18 renders first-time onboarding with everyday-surface links only', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.7', 'Dashboard hides onboarding once an approved statement and posted journal entry exist', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC16.12.19 hides first-time onboarding after approved statement and posted journal entry exist', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.8', 'Reports page renders all report cards with links for available reports', 'apps/frontend/src/__tests__/reportsPage.test.tsx::AC16.12.11 renders the four front reports and the More reports with links', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.9', 'Reports page displays accounting equation section content', 'apps/frontend/src/__tests__/reportsPage.test.tsx::AC16.12.12 displays accounting equation section', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.10', 'Balance-sheet page renders loading and error retry states', 'apps/frontend/src/__tests__/balanceSheetPage.test.tsx::AC16.14.1 renders loading and error retry states', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.11', 'Balance-sheet page renders totals and account sections on successful fetch', 'apps/frontend/src/__tests__/balanceSheetPage.test.tsx::AC16.14.2 / test_AC8_13_48 renders string totals and refetches by date', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.12', 'Balance-sheet page toggles account tree expansion controls', 'apps/frontend/src/__tests__/balanceSheetPage.test.tsx::AC16.14.3 toggles tree expansion controls', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.13', 'Income-statement page renders loading and error retry states', 'apps/frontend/src/__tests__/incomeStatementPage.test.tsx::AC16.14.4 renders loading and error retry states', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.14', 'Income-statement page renders KPI cards and category lists on success', 'apps/frontend/src/__tests__/incomeStatementPage.test.tsx::AC16.14.5 / test_AC8_13_48 renders string KPI cards and category lists', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.15', 'Income-statement page tag filters can be selected and cleared', 'apps/frontend/src/__tests__/incomeStatementPage.test.tsx::AC16.14.6 supports selecting and clearing tags', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.16', 'Cash-flow page renders loading and error retry states', 'apps/frontend/src/__tests__/cashFlowPage.test.tsx::AC16.14.7 renders loading and error retry states', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.17', 'Cash-flow page renders summary and section cards on success', 'apps/frontend/src/__tests__/cashFlowPage.test.tsx::AC16.14.8 / test_AC8_13_48 renders string summary and activity sections', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.18', 'Cash-flow page renders sankey chart when summary exists', 'apps/frontend/src/__tests__/cashFlowPage.test.tsx::AC16.14.9 renders sankey chart when summary exists', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.19', 'Bar and pie chart components render semantic labels and filtered data', 'apps/frontend/src/__tests__/chartsComponents.test.tsx::AC16.19.10 bar chart and pie chart render labels and filtered segments', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.20', 'Trend chart renders line/area paths and point labels for provided series', 'apps/frontend/src/__tests__/chartsComponents.test.tsx::AC16.19.11 trend chart renders point labels and svg paths', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.21', 'Sankey chart builds empty-state and data-state options for inflow and outflow links', 'apps/frontend/src/__tests__/sankeyChartComponent.test.tsx::AC16.21.7 renders empty-state option when no series data is provided', priority='P2'),
        ac('AC-reporting.fe-report-surfaces.22', 'Sankey chart recomputes theme-aware colors when root theme attributes change', 'apps/frontend/src/__tests__/sankeyChartComponent.test.tsx::AC16.21.8 recomputes theme-driven colors on root attribute change', priority='P2'),
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-022
        # (everyday-user-ia) and EPIC-005 (reporting-visualization) ──
        ac('AC-reporting.fe-viz-reports.1', "Annualized income KPI dashboard card renders the endpoint's figures (backend endpoint half migrated as `AC-reporting.kpis.1`; calculation ownership migrated to the `reporting` package roadmap as `AC-reporting.annualized-dashboard.1`, #1821 Wave A)", 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC11.8.2/AC11.8.6/AC5.6.4 renders Annualized Income card with the four metric labels'),
        ac('AC-reporting.fe-ia-reports.1', 'The authenticated Home renders financial key numbers, an action-required summary, and a quick-upload entry', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC16.12.3 AC22.1.2 renders KPI, chart, activity, and alert sections when API succeeds', priority='P1'),
        ac('AC-reporting.fe-viz-reports.2', 'Personal report package renders the `investment_performance` report section from the EPIC-017 schedule API (backend contract half migrated as `AC-reporting.package-investment.1`)', 'apps/frontend/src/__tests__/portfolioPage.test.tsx::AC5.8.1 renders investment performance report schedule from the schedule API'),
        ac('AC-reporting.fe-ia-reports.2', 'The `/reports` front section renders exactly four report blocks: Balance Sheet, Income Statement, Annualized Income, and Reconciliation coverage (reconciliation match rate / unmatched count)', 'apps/frontend/src/__tests__/reportsCockpit.test.tsx::AC22.3.1 leads with exactly the four everyday report blocks and their live figures', priority='P1'),
        ac('AC-reporting.fe-viz-reports.3', 'Frontend personal package page renders the contract section IDs and labels from the API contract', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC5.9.3 renders personal package contract sections from API'),
        ac('AC-reporting.fe-ia-reports.3', 'All other reports (Cash Flow, Personal Report Package, and any future reports) live behind a single "More" control, not the front section', 'apps/frontend/src/__tests__/reportsCockpit.test.tsx::AC22.3.2 keeps Cash Flow and the Personal Report Package behind the More control', priority='P1'),
        ac('AC-reporting.fe-viz-reports.4', 'Frontend/export contract surfaces stable export format and CSV columns for package consumers', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC5.9.4 renders export contract metadata', priority='P1'),
        ac('AC-reporting.fe-ia-reports.4', 'A reusable lineage drill-down component lets a user click any amount on the Balance Sheet or Income Statement, list the contributing journal lines, and open the full evidence chain (journal line → bank statement transaction → atomic transaction → source document)', 'apps/frontend/src/__tests__/balanceSheetDrilldown.test.tsx::AC22.3.4 lists contributing journal lines and opens the lineage chain for one', priority='P1'),
        ac('AC-reporting.fe-viz-reports.5', 'Frontend personal package page renders annualized income totals and restricted treatment from the schedule endpoint', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC5.11.2 renders annualized income schedule values and restricted treatment'),
        ac('AC-reporting.fe-ia-reports.5', 'Accounts/amounts with no contributing lines or no graph-compatible anchor degrade gracefully with an explicit empty/"no source linked" state and no crash', 'apps/frontend/src/__tests__/balanceSheetDrilldown.test.tsx::AC22.3.5 shows an empty state when no transactions contribute', priority='P1'),
        ac('AC-reporting.fe-viz-reports.6', 'Frontend personal package page renders notes and disclosure basis from the notes endpoint', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC5.12.3 renders package notes and disclosure basis'),
        ac('AC-reporting.fe-ia-reports.6', 'Desktop and mobile smoke covers the four-block cockpit and a Balance Sheet drill-down open/close without layout overflow', 'apps/frontend/playwright/reports-cockpit.spec.ts::${label} shows the four blocks and drills a balance-sheet amount', priority='P1'),
        ac('AC-reporting.fe-viz-reports.7', 'Frontend personal package page renders source, ledger, review, and identifier metadata from the appendix', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC5.13.3 AC5.16.3 AC5.16.4 renders traceability appendix source, ledger, review, and identifiers'),
        ac('AC-reporting.fe-ia-reports.7', 'The Home (`/`) defaults to a lean view (action-required summary, financial key numbers, quick upload) with heavy analytics/charts behind an opt-in toggle', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC22.4.4 defaults to a lean Home with heavy analytics behind an opt-in toggle', priority='P1'),
        ac('AC-reporting.fe-viz-reports.8', 'Balance sheet page exposes the restricted-holdings include toggle and renders equation component detail (backend default-exclusion half migrated as `AC-reporting.trust-signals.1`; (AC16.14.2 removed, canonical: the same shared test also proves migrated to reporting package roadmap, #1821 Wave B))', 'apps/frontend/src/__tests__/balanceSheetPage.test.tsx::AC16.14.2 / test_AC8_13_48 renders string totals and refetches by date'),
        ac('AC-reporting.fe-ia-reports.8', 'E2E: an amount on the Balance Sheet drills down to its contributing journal lines and on to the source document', 'apps/frontend/playwright/epic022-drilldown-journey.spec.ts::${label}: a Balance Sheet amount drills to its contributing line and on to the source document', priority='P1'),
        ac('AC-reporting.fe-viz-reports.9', 'Balance sheet, income statement, and cash-flow report pages surface backend `fx_warnings` instead of silently rendering partial totals (backend fx_warnings-preservation half migrated as `AC-reporting.trust-signals.2`)', 'apps/frontend/src/__tests__/balanceSheetPage.test.tsx::AC16.14.2 / test_AC8_13_48 renders string totals and refetches by date'),
        ac('AC-reporting.fe-ia-reports.9', 'The Home surfaces a single primary next-action with overlapping reconciliation links de-duplicated, and the Chat page heading reads "AI Advisor"', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC22.16.2 AC22.5.6 routes the risk radar and unmatched CTA to the unified /attention queue', priority='P1'),
        ac('AC-reporting.fe-viz-reports.10', 'Personal report package traceability renders concrete source and ledger identifiers when the appendix provides them', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC5.13.3 AC5.16.3 AC5.16.4 renders traceability appendix source, ledger, review, and identifiers'),
        ac('AC-reporting.fe-ia-reports.10', "Clicking a cash-flow amount opens the account-lineage drawer for that account's contributing journal lines (the backend account-anchor half migrated to the `reporting` package roadmap as `AC-reporting.lineage.2`, migration closeout continuation, #1663 / #1716; the frontend drawer half stays here)", 'apps/frontend/src/__tests__/cashFlowPage.test.tsx::AC22.7.1 drills a cash-flow amount down to its account lineage', priority='P1'),
        ac('AC-reporting.fe-viz-reports.11', 'Personal report package page exposes an authenticated CSV export action after framework selection, using the package export contract and selected framework ID', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC5.17.2 downloads package CSV through authenticated apiDownload'),
        ac('AC-reporting.fe-ia-reports.11', 'The reusable lineage panel renders evidence nodes as an ordered source-to-report path with per-hop source, confidence, and version badges when those fields are available', 'apps/frontend/src/__tests__/lineagePanel.test.tsx::AC22.7.2 renders an ordered lineage path with source, confidence, and version badges', priority='P1'),
        ac('AC-reporting.fe-viz-reports.12', 'The package page shows recent snapshots, can generate a new snapshot, and downloads JSON/CSV from the saved snapshot artifact', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC5.19.4 generates and downloads package snapshots'),
        ac('AC-reporting.fe-ia-reports.12', 'The Cash Flow statement renders a reconciliation that ties beginning cash + net cash flow to ending cash, and explicitly flags when it does not reconcile', 'apps/frontend/src/__tests__/cashFlowPage.test.tsx::AC22.7.3 flags cash that does not tie (beginning + net != ending)', priority='P1'),
        ac('AC-reporting.fe-viz-reports.13', '`ReportPageShell` renders title, description, and toolbar slot, and shows the report body when not loading or errored', 'apps/frontend/src/__tests__/reportPageShell.test.tsx::AC5.33.1 renders title, description, toolbar, and body content', priority='P1'),
        ac('AC-reporting.fe-ia-reports.13', 'Desktop and mobile Playwright smoke covers Cash Flow amount drill-down opening the account-lineage drawer without document horizontal overflow', 'apps/frontend/playwright/cash-flow-drilldown.spec.ts::${scenario.name} opens account-lineage drawer from a cash-flow amount', priority='P1'),
        ac('AC-reporting.fe-viz-reports.14', '`ReportPageShell` renders the loading skeleton (and not the body) while `isLoading`', 'apps/frontend/src/__tests__/reportPageShell.test.tsx::AC5.33.2 shows loading skeleton while loading', priority='P1'),
        ac('AC-reporting.fe-ia-reports.14', 'The report package titles its sections with human-readable labels (Reporting Framework, Report Readiness, Source Trust, Framework Policy, schedules, Traceability Appendix) rather than developer-facing snake_case identifiers', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC22.8.1 titles package sections with human labels, not developer snake_case identifiers', priority='P1'),
        ac('AC-reporting.fe-viz-reports.15', '`ReportPageShell` renders the error message with a working Retry action on `isError`', 'apps/frontend/src/__tests__/reportPageShell.test.tsx::AC5.33.3 shows error message and retries on click', priority='P1'),
        ac('AC-reporting.fe-ia-reports.15', 'The loaded report package starts with a readable cover sheet and table of contents that expose the package id, selected framework, report date, and linked human section titles', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC22.8.2 AC22.13.3 renders a readable package cover and linked table of contents', priority='P1'),
        ac('AC-reporting.fe-viz-reports.16', '`ReportToolbar` composes the AI-prompt action, Home link, and CSV export action from its props', 'apps/frontend/src/__tests__/reportToolbar.test.tsx::AC5.33.4 renders AI prompt, home link, and caller-provided export control', priority='P1'),
        ac('AC-reporting.fe-ia-reports.16', 'The unselected-framework and framework-package loading states reserve the package layout with guidance or skeleton placeholders, never a blank text-only pre-selection or loading screen', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC20.6.1 AC22.8.3 AC22.13.3 requires explicit framework selection before loading framework-scoped package output', priority='P1'),
        ac('AC-reporting.fe-viz-reports.17', '`AiPromptAction` links to the chat route with a URL-encoded prompt', 'apps/frontend/src/__tests__/reportToolbar.test.tsx::AC5.33.5 links to chat with url-encoded prompt', priority='P1'),
        ac('AC-reporting.fe-ia-reports.17', 'Desktop and mobile Playwright smoke covers report-package framework selection, cover, table of contents, readiness, and no document horizontal overflow', 'apps/frontend/playwright/report-readiness.spec.ts::${scenario.name} renders cover, contents, and readiness before package output', priority='P1'),
        ac('AC-reporting.fe-viz-reports.18', '`DateFilterControl` renders a labelled date input and emits changes', 'apps/frontend/src/__tests__/reportFilters.test.tsx::AC5.34.1 renders labelled date input and emits change', priority='P1'),
        ac('AC-reporting.fe-ia-reports.18', "The Reports cockpit's reconciliation-coverage block stays in the reports context and does not link into the Advanced `/reconciliation` surface", 'apps/frontend/src/__tests__/reportsCockpit.test.tsx::AC22.9.1 keeps the reconciliation-coverage block in the reports context, not linked into Advanced', priority='P1'),
        ac('AC-reporting.fe-viz-reports.19', '`CurrencyFilterControl` renders a labelled currency select with the provided options and emits changes', 'apps/frontend/src/__tests__/reportFilters.test.tsx::AC5.34.2 renders currency options and emits change', priority='P1'),
        ac('AC-reporting.fe-ia-reports.19', 'The "Annualized Income" cockpit card\'s destination matches its label (it opens the report package and the caption says so), with no silent label/destination mismatch', "apps/frontend/src/__tests__/reportsCockpit.test.tsx::AC22.9.3 makes the Annualized Income card's destination match its label", priority='P1'),
        ac('AC-reporting.fe-viz-reports.20', '`useReportFilters` builds a query string from its date and currency state', 'apps/frontend/src/__tests__/useReportFilters.test.ts::AC5.34.3 builds query string from filter state', priority='P1'),
        ac('AC-reporting.fe-ia-reports.20', 'The Home getting-started steps link only to everyday surfaces — the first step targets `/upload` and no step links to the accounting-jargon `/accounts` route', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC22.16.1 AC16.12.17 AC16.12.18 renders first-time onboarding with everyday-surface links only', priority='P1'),
        ac('AC-reporting.fe-viz-reports.21', '`useReportFilters` derives the CSV export path for the given report type', 'apps/frontend/src/__tests__/useReportFilters.test.ts::AC5.34.4 derives csv export path for report type', priority='P1'),
        ac('AC-reporting.fe-ia-reports.21', 'The Home presents a single confidence-ranked attention entry point: the analytics reconciliation ("Risk radar") card and the unmatched-alerts call-to-action link to the unified `/attention` queue instead of parallel Advanced reconciliation internals (`/reconciliation`, `/reconciliation/unmatched`, `/review`)', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC22.16.2 AC22.5.6 routes the risk radar and unmatched CTA to the unified /attention queue', priority='P1'),
        ac('AC-reporting.fe-viz-reports.22', '`useReportFilters` updates the query string when the currency changes', 'apps/frontend/src/__tests__/useReportFilters.test.ts::AC5.34.5 updates query string when currency changes', priority='P1'),
        ac('AC-reporting.fe-ia-reports.22', '`useDashboardData` is composed from independently-usable hooks (`useDashboardSnapshot` for the financial/reconciliation aggregate and `useAssetTrend` for the per-account trend), each callable on its own through the shared `apiFetch` transport, while the aggregate hook preserves its existing public result contract', 'apps/frontend/src/__tests__/useDashboardData.test.ts::AC22.16.3 composes the snapshot and asset-trend hooks, exposing the trend once the balance loads', priority='P1'),
        ac('AC-reporting.fe-viz-reports.23', '`useReportFilters` seeds its initial date/currency state from the URL query params (`as_of_date`/`start_date`/`end_date`/`currency`) with precedence explicit option > URL param > default, so report routes honour deep links', 'apps/frontend/src/__tests__/useReportFilters.test.ts::AC5.34.6 seeds initial filter state from URL query params', priority='P1'),
        ac('AC-reporting.fe-ia-reports.23', 'The loaded report package uses reader-facing labels for evidence coverage, reporting basis, and traceability summary, with proof-system labels such as `Deterministic PR`, `Post-merge LLM/OCR`, `Framework Policy`, raw gap codes, raw blocker codes, and policy result IDs kept out of the primary visible layer', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC22.19.1 renders the loaded package with reader-first labels before proof internals', priority='P1'),
        ac('AC-reporting.fe-viz-reports.24', '`useDashboardData` aggregates the dashboard endpoints over `apiFetch` and exposes a single loading flag', 'apps/frontend/src/__tests__/useDashboardData.test.ts::AC5.35.1 aggregates dashboard endpoints over apiFetch', priority='P1'),
        ac('AC-reporting.fe-ia-reports.24', 'Explicit `Audit details` disclosures keep the same source-trust, framework-policy, traceability, blocker, matrix-version, line-id, confidence, review-state, and evidence-reference details keyboard reachable and screen-reader comprehensible', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC22.19.2 keeps proof and policy internals in keyboard-reachable audit details', priority='P1'),
        ac('AC-reporting.fe-viz-reports.25', '`useDashboardData` normalizes missing balance-sheet / income / annualized fields to safe decimal-string defaults', 'apps/frontend/src/__tests__/useDashboardData.test.ts::AC5.35.2 normalizes missing report fields to defaults', priority='P1'),
        ac('AC-reporting.fe-ia-reports.25', 'Print/save and export metadata default to the reader-first hierarchy; raw CSV columns, policy result IDs, matrix version, and evidence bundle references are available only in an explicit audit/export-details disclosure', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC22.19.3 keeps export proof metadata behind a print-hidden export audit disclosure', priority='P1'),
        ac('AC-reporting.fe-viz-reports.26', '`useDashboardData` surfaces an error message and a retry that refetches when aggregation fails', 'apps/frontend/src/__tests__/useDashboardData.test.ts::AC5.35.3 surfaces error and retries on failure', priority='P1'),
        ac('AC-reporting.fe-ia-reports.26', 'The Home renders the net-worth headline, a three-statement segmented entry (Balance Sheet / Income / Cash Flow) each deep-linking to its full report, the single next-action, the attention bell, and keeps heavy charts behind an opt-in toggle', 'apps/frontend/src/__tests__/homeStatements.test.tsx::deep-links each of the three statements to its full report', priority='P1'),
        ac('AC-reporting.fe-viz-reports.27', '`useDashboardData` tolerates a failing chat-suggestions endpoint without failing the whole dashboard', 'apps/frontend/src/__tests__/useDashboardData.test.ts::AC5.35.4 tolerates failing chat suggestions endpoint', priority='P1'),
        ac('AC-reporting.fe-viz-reports.28', 'Net worth chart component on dashboard renders ECharts line chart with date X-axis and net-worth Y-axis', 'apps/frontend/src/__tests__/uiGapAudit.netWorthTimeSeries.test.tsx::AC5.7.2/AC5.7.6 mounts an ECharts-backed net worth line chart', priority='P2'),
        ac('AC-reporting.fe-viz-reports.29', 'Time range selector (1M / 3M / 6M / 1Y / All) on dashboard toggles `from` parameter for chart', 'apps/frontend/src/__tests__/uiGapAudit.netWorthTimeSeries.test.tsx::AC5.7.4 range selector toggles the from parameter and re-fetches', priority='P2'),
        ac('AC-reporting.fe-viz-reports.30', 'Empty-state placeholder rendered when fewer than 2 data points exist (cannot draw line)', 'apps/frontend/src/__tests__/uiGapAudit.netWorthTimeSeries.test.tsx::AC5.7.5 renders an empty state when fewer than two points exist', priority='P2'),
        ac('AC-reporting.fe-viz-reports.31', 'Frontend unit test mounts NetWorthTimeSeries component and asserts chart container exists', 'apps/frontend/src/__tests__/uiGapAudit.netWorthTimeSeries.test.tsx::AC5.7.2/AC5.7.6 mounts an ECharts-backed net worth line chart', priority='P2'),
        ac('AC-reporting.fe-viz-reports.32', 'The Reports cockpit renders package readiness state, blocker count, next action, and source-gap summary before report cards', 'apps/frontend/src/__tests__/reportsCockpit.test.tsx::AC5.37.1 renders trust-first readiness before report cards', priority='P1'),
        ac('AC-reporting.fe-viz-reports.33', 'If readiness loading fails, the Reports cockpit shows a contained unavailable state while preserving report navigation.', 'apps/frontend/src/__tests__/reportsCockpit.test.tsx::AC5.37.2 preserves report navigation when readiness is unavailable', priority='P1', vision_anchor='non-goals-not-budgeting-app'),
        # ── Wave B (#1821): frontend-proof rows migrated from the
        # remaining EPIC files (EPIC-001/002/004/008/011/012/015/017/018/019/021/024/025) ──
        ac('AC-reporting.fe-remainder-reports.1', 'The report package traceability surface exposes a lineage panel from at least one report traceability row', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC18.9.4 AC18.9.5 AC18.9.6 opens an Evidence Graph lineage panel from report traceability', priority='P2'),
        ac('AC-reporting.fe-remainder-reports.2', 'The lineage panel renders source document, extracted record, atomic fact, ledger entry, ledger line, and report-line anchors when present', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC18.9.4 AC18.9.5 AC18.9.6 opens an Evidence Graph lineage panel from report traceability', priority='P2'),
        ac('AC-reporting.fe-remainder-reports.3', 'Tests cover report line to source document navigation and source document to impacted ledger/report navigation', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC18.9.4 AC18.9.5 AC18.9.6 opens an Evidence Graph lineage panel from report traceability', priority='P2'),
        ac('AC-reporting.fe-remainder-reports.4', 'Dashboard status feed renders primary state, report readiness, recent automation, blocker/action severity, and an empty no-action state without raw audit-log noise', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC19.3.6 renders the workflow status feed on the dashboard landing surface'),
        ac('AC-reporting.fe-remainder-reports.5', 'The first dashboard viewport renders the upload-to-report workflow home before KPI, chart, and activity content', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC19.4.2 AC16.16.1 renders the upload-to-report home before secondary dashboard metrics'),
        ac('AC-reporting.fe-remainder-reports.6', 'The dashboard primary CTA follows `workflow.status.next_action.href` and labels upload as the default action when no higher-priority blocker/action exists', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC19.4.3 follows workflow next_action for blocker and upload primary CTAs'),
        ac('AC-reporting.fe-remainder-reports.7', 'Report readiness state and blocker count are visible above secondary dashboard metrics and link to the readiness/report action path', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC19.4.4 renders report readiness above analytics with blocker count and link'),
        ac('AC-reporting.fe-remainder-reports.8', 'Recent workflow events are visible, grouped by actionability, and routine automation is summarized without dominating the page', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC19.4.5 shows actionable recent events and summarizes routine automation'),
        ac('AC-reporting.fe-remainder-reports.9', 'Secondary dashboard metric API failure does not hide the workflow home; the analytics section renders an isolated retry/error state', 'apps/frontend/src/__tests__/dashboardPage.test.tsx::AC19.4.6 keeps upload-to-report home visible when secondary analytics fail'),
        ac('AC-reporting.fe-remainder-reports.10', 'Desktop and mobile Playwright smoke covers the upload-first dashboard entry without layout overflow', 'apps/frontend/playwright/upload-first-dashboard.spec.ts::${scenario.name} renders upload-to-report home before secondary analytics'),
        ac('AC-reporting.fe-remainder-reports.11', 'Personal report package page renders readiness state and blocker links before package section output', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC19.5.4 renders package readiness before report package output', priority='P1'),
        ac('AC-reporting.fe-remainder-reports.12', 'Personal report package page renders non-blocked readiness states without stale blocker cards', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC19.5.5 renders non-blocked readiness states without blocker cards', priority='P1'),
        ac('AC-reporting.fe-remainder-reports.13', 'Report readiness has route-level Playwright smoke coverage before package output', 'apps/frontend/playwright/report-readiness.spec.ts::${scenario.name} renders cover, contents, and readiness before package output', priority='P1'),
        ac('AC-reporting.fe-remainder-reports.14', 'Personal report package page renders decision authority coverage before detailed traceability output', 'apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC19.9.2 renders decision authority coverage before traceability details'),
        ac('AC-reporting.report-integrity.1', 'Processing identity retains visible in-transit assets through zero, outstanding and settled balances in both framework reports without changing cash-flow neutrality.', 'apps/backend/tests/reporting/test_report_integrity.py::test_processing_survives_framework_reporting', proof_kind='exact'),
        ac('AC-reporting.report-integrity.2', 'Authoritative account opening stock effective at the report start enters beginning cash without being presented as period cash activity, including explicit zero and translated foreign-currency positions.', 'apps/backend/tests/reporting/test_report_integrity.py::test_opening_stock_is_beginning_cash', proof_kind='exact'),
        ac('AC-reporting.report-integrity.3', 'First stock observed after the selected period start is separately disclosed as a stock adjustment with an explicit coverage blocker; spoofed or unproven opening labels never authorize starting stock.', 'apps/backend/tests/reporting/test_report_integrity.py::test_midperiod_opening_is_explicit_incomplete_coverage', proof_kind='exact'),
        ac('AC-reporting.report-integrity.4', 'Framework income lines preserve authorized posted economic categories and exactly reconcile mixed-category account amounts in both personal frameworks.', 'apps/backend/tests/reporting/test_report_integrity.py::test_posted_categories_survive_framework_mapping', proof_kind='exact'),
        ac('AC-reporting.report-integrity.5', 'Missing or unsupported posted categories stay explicitly other income or expense rather than acquiring investment meaning from an account name or broad type.', 'apps/backend/tests/reporting/test_report_integrity.py::test_uncategorized_history_is_not_investment_activity', proof_kind='exact'),
        ac('AC-reporting.report-integrity.6', 'Archiving accounts never removes their posted historical amounts, cash identities, valuation basis or FX revaluation from period reports.', 'apps/backend/tests/reporting/test_report_integrity.py::test_archiving_preserves_historical_reports', proof_kind='exact'),
        ac('AC-reporting.report-integrity.7', 'Persisted source-backed ledger facts remain correctly classified and usable through package generation, frozen reopening and export after reconciliation.', 'apps/backend/tests/reporting/test_report_integrity.py::test_persisted_package_integrity', proof_kind='exact'),
        ac('AC-reporting.report-integrity.8', 'A midperiod package retains current decision-backed statement lineage for included movements without admitting future closing stock or transactions; empty source anchors are explicitly unavailable.', 'apps/backend/tests/reporting/test_midperiod_source_lineage.py::test_midperiod_source_lineage_preserves_cutoff', proof_kind='exact'),
        ac('AC-reporting.cash-events.1', 'Only journal entries touching an exact cash identity can produce cash-flow activity; non-cash accruals and financed asset acquisitions produce none.', 'apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_1_only_cash_touch_events_are_classified', proof_kind='exact'),
        ac('AC-reporting.cash-events.2', 'Cash events are classified only from unambiguous full-event evidence with authoritative producer provenance; broad balance-sheet types and caller-supplied semantics remain unclassified while settlement still enters the bridge.', 'apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_2_event_classification_is_authoritative', proof_kind='exact'),
        ac('AC-reporting.cash-events.3', 'Direct and Processing-mediated internal transfers among cash and cash-equivalent identities emit no operating, investing, or financing activity.', 'apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_3_internal_transfers_are_neutral', proof_kind='exact'),
        ac('AC-reporting.cash-events.4', 'The cash bridge separately discloses classified activity, unclassified cash, and FX effect and proves that they equal ending cash less beginning cash.', 'apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_4_cash_bridge_ties_exactly', proof_kind='exact'),
        ac('AC-reporting.cash-events.5', 'Every cash-event query predicates both JournalEntry.user_id and Account.user_id and rejects an entry containing any foreign-tenant account line.', 'apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_5_dual_tenant_predicates_reject_hostile_entries', proof_kind='exact'),
        ac('AC-reporting.cash-events.6', 'generate_cash_flow is the single reporting-owned cash projection used by standalone and package consumers.', 'apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_6_one_projection_serves_every_cash_flow_consumer', proof_kind='exact'),
        ac('AC-reporting.cash-events.7', 'Exact cash identities plus anchored event decisions produce proven output; lexical discovery or an unanchored contributing event is explicitly unproven and cannot authorize a package.', 'apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_7_consumer_proof_state_is_explicit', proof_kind='exact'),
        ac('AC-reporting.cash-events.8', 'Each classified or unclassified cash event exposes exact journal-entry, journal-line, source, decision-anchor, and event-semantic evidence used by the projection.', 'apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_8_event_lineage_exposes_ledger_and_decision_anchors', proof_kind='exact'),
        ac('AC-reporting.cash-events.9', 'Package governance detail projects the exact detector, proof strength, target SHA, issue, and existing enforcing gate for every cash-event guarantee.', 'apps/backend/tests/reporting/test_cash_event_governance.py::test_AC_reporting_cash_events_9_governance_detail_is_package_owned_and_enforced', proof_kind='exact'),
        ac('AC-reporting.cash-events.10', 'The adversarial cash-event matrix locks non-cash, settlement, transfer, FX, void, and hostile-tenant counterfactuals against regression.', 'apps/backend/tests/reporting/test_cash_event_governance.py::test_AC_reporting_cash_events_10_counterfactual_matrix_is_locked', proof_kind='exact'),
        ac('AC-reporting.cash-events.11', 'Cash flow bridge fx_effect is calculated independently from foreign-currency cash rate variances without circular plugging, exposing discrepancy and failing reconciliation when cash activities are omitted or corrupted.', 'apps/backend/tests/reporting/test_falsifiable_cash_flow.py::test_multicurrency_cash_bridge_exposes_discrepancy_on_missing_activity', priority='P1'),
    ],
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
    concepts=[
        ConceptRecord(
            key="framework_reporting",
            owner="common/reporting/framework-reporting.md",
            description=(
                "US-like and HK-like target-backward policy layer for personal report "
                "packages."
            ),
            cross_refs=[
                "common/reporting/reporting.md",
                "common/ledger/readme.md",
                "docs/project/EPIC-020.framework-aware-personal-reporting.md",
            ],
            family="reporting",
            kind="concept",
        ),
        ConceptRecord(
            key="reporting_calculations",
            owner="common/reporting/readme.md",
            description="Financial reports, multi-currency consolidation, calculations.",
            cross_refs=[
                "common/reporting/reporting.md",
                "common/ledger/readme.md",
                "common/pricing/market_data.md",
            ],
            family="reporting",
            kind="concept",
        ),
    ],
)
# fmt: on
