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
    ACRecord,
    ConceptRecord,
    GovernanceGuarantee,
    GovernanceInitiative,
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
        "current_package_document_summary",
        "AnnualizedIncomeTotals",
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
        ACRecord(
            id="AC-reporting.fx-port.1",
            statement=(
                "Reporting's FX gateway exposes exact rate, conversion, and prefetch "
                "protocols without Callable[..., Any] or variadic Any forwarders."
            ),
            test=(
                "tests/tooling/test_s3_pr_d_structure.py"
                "::test_AC_s3_typed_fx_ports_have_no_erased_registration_or_forwarders"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.snapshot-ownership.1",
            statement=(
                "ReportSnapshot and ReportType are published and mapped by reporting; "
                "extraction defines and exports neither."
            ),
            test=(
                "tests/tooling/test_s3_pr_d_structure.py"
                "::test_AC_reporting_snapshot_ownership_and_metadata_registration"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.vocabulary-ownership.1",
            statement=(
                "PersonalReportingFrameworkId, ReportLineId, and "
                "PolicyDimension are reporting-owned base value objects; the "
                "delivery schema may only re-export those exact definitions."
            ),
            test=(
                "tests/tooling/test_vocabulary_ownership.py"
                "::test_AC_reporting_vocabulary_ownership_1_reporting_owns_wire_enums"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.single-owner.1",
            statement=(
                "Manual-valuation line naming is defined only by pricing, its fact owner; "
                "reporting contains no dead duplicate helper that can drift independently."
            ),
            test=(
                "apps/backend/tests/reporting/test_reporting_calc_extraction.py"
                "::test_AC_reporting_single_owner_1_has_no_valuation_line_name_copy"
            ),
            priority="P1",
            status="done",
        ),
        # ── opening-balance confidence-tier gate (was EPIC-002 AC2.16.4 —
        # EPIC-002 never owned this behavior; it's report assembly, not
        # double-entry posting) ──
        ACRecord(
            id="AC-reporting.opening-balance.1",
            statement=(
                "A balance sheet with posted activity but no recorded opening balance emits an "
                "opening_balance_warnings entry (type=missing_opening_balance), and the package "
                "assembler treats it as a deterministic blocker."
            ),
            # was AC2.16.4
            test=(
                "apps/backend/tests/reporting/test_balance_sheet_opening_balance_gate.py"
                "::test_AC2_16_4_balance_sheet_warns_when_opening_balance_missing"
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
                "The net-worth allocation schedule surfaces the same "
                "opening_balance_warnings as the balance sheet "
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
                "tests/tooling/test_framework_reporting_epic_contract.py"
                "::test_AC20_6_1_ai_suggestions_require_structured_reviewed_policy_fields"
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
        ACRecord(
            id="AC-reporting.balance-sheet.5",
            statement=(
                "A historical as_of_date balance sheet excludes a portfolio position "
                "whose ManagedPosition.acquisition_date postdates that as_of_date "
                "(consistent with portfolio's documented point-in-time holdings rule: "
                "future snapshots are never used); the same position appears once "
                "as_of_date reaches its acquisition_date."
            ),
            test=(
                "tests/e2e/test_personal_financial_report_package.py"
                "::test_personal_financial_report_package_post_merge_journey"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-reporting.balance-sheet.6",
            statement=(
                "A manual valuation component recorded only after the "
                "report's as_of_date stays out of the balance-sheet totals "
                "AND is disclosed in the response's portfolio_warnings, so a "
                "historical balance sheet never silently reads as complete "
                "(#1796)."
            ),
            test=(
                "apps/backend/tests/reporting/test_reporting_net_worth_components.py"
                "::test_AC_reporting_balance_sheet_6_valuation_gap_disclosed_in_portfolio_warnings"
            ),
            priority="P1",
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
                "The document-embedded package contract defines the required section IDs, "
                "labels, owners, and source semantics."
            ),
            # was AC5.9.1
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC5_9_1_package_contract_defines_required_sections"
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
                "The package contract requires the typed annualized_income_long_term section "
                "inside PersonalReportPackageDocument."
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
                "::test_AC_reporting_package_document_4_exports_the_selected_frozen_document"
            ),
            priority="P0",
            status="done",
        ),
        # ── group package-document: one typed delivery artifact (#567) ──
        ACRecord(
            id="AC-reporting.package-document.1",
            statement=(
                "The personal report package is a versioned, Decimal-safe document with "
                "required typed balance-sheet, income-statement, cash-flow, investment, "
                "annualized-income, notes, traceability, and immutable input-manifest sections."
            ),
            test=(
                "apps/backend/tests/reporting/test_package_document.py"
                "::test_AC_reporting_package_document_1_requires_typed_delivery_sections"
            ),
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.package-document.2",
            statement=(
                "Preview, generation, persistence, reopen, and export use the one "
                "PackageAssembler document path; the reports router cannot retain a private "
                "section aggregator or live package export branch."
            ),
            test=(
                "apps/backend/tests/reporting/test_package_document.py"
                "::test_AC_reporting_package_document_2_has_one_assembler_and_no_live_package_export"
            ),
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.package-document.3",
            statement=(
                "Trusted/final package state is the projection of one persisted CODE-ONLY "
                "TraceRecord MANIFEST decision over the exact current contributing decisions "
                "and deterministic section observation; missing, stale, legacy, or superseded "
                "inputs produce draft/blocked output and no trusted decision."
            ),
            test=(
                "apps/backend/tests/reporting/test_package_document.py"
                "::test_AC_reporting_package_document_3_trust_is_one_trace_decision_fold"
            ),
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.package-document.4",
            statement=(
                "A selected frozen document is the only JSON/CSV export input; a live-data "
                "mutation after generation cannot change the exported identity, totals, "
                "traceability, or typed section payloads."
            ),
            test=(
                "apps/backend/tests/api/test_personal_report_package_contract.py"
                "::test_AC_reporting_package_document_4_exports_the_selected_frozen_document"
            ),
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-reporting.package-document.5",
            statement=(
                "Package decision emission and frozen snapshot persistence share the caller-owned "
                "transaction, so a failure after trace flush leaves neither TraceRecord nor snapshot."
            ),
            test=(
                "apps/backend/tests/reporting/test_package_document.py"
                "::test_AC_reporting_package_document_5_trace_and_snapshot_rollback_together"
            ),
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.package-document.6",
            statement=(
                "A whole-production-tree certificate permits one PackageDocument producer, forbids "
                "consumer-owned readiness/trust calculations and live selected-snapshot reads, and "
                "requires reports, statements, workflow, advisor, and frontend package surfaces to "
                "consume the same document or its typed projection."
            ),
            test=(
                "apps/backend/tests/reporting/test_package_document.py"
                "::test_AC_reporting_package_document_6_producer_and_consumer_closure"
            ),
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.package-document.7",
            statement=(
                "PackageAssembler adapts extraction, ledger, and pricing inputs into one typed "
                "PackageSectionContribution shape and folds only those exact decision/input refs "
                "into the manifest. The traceability appendix renders the same contribution set; "
                "raw foreign-package rows and display labels cannot authorize a package."
            ),
            test=(
                "apps/backend/tests/reporting/test_package_document.py"
                "::test_AC_reporting_package_document_7_manifest_folds_only_typed_contributions"
            ),
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.package-document.8",
            statement=(
                "The PackageDocument cash-flow section receives an exact typed set of cash-balance "
                "account identities from authoritative bank-statement contributions. Account names "
                "cannot classify package cash, and missing or ambiguous cash inputs block trusted output."
            ),
            test=(
                "apps/backend/tests/reporting/test_financial_logic_audit.py"
                "::test_AC_reporting_package_document_8_uses_exact_cash_inputs_not_account_names"
            ),
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.package-document.9",
            statement=(
                "Every authoritative PackageSectionContribution carries one typed audit decision "
                "reference containing its exact target and assertion. Package assembly accepts the "
                "contribution only when the current tenant projection matches all three coordinates; "
                "missing, cross-scope, stale, target-mismatched, or assertion-mismatched decisions "
                "remain unproven."
            ),
            test=(
                "apps/backend/tests/reporting/test_package_document.py"
                "::test_AC_reporting_package_document_9_requires_exact_decision_coordinates"
            ),
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.package-document.10",
            statement=(
                "Reporting publishes one pure package-decision coordinate builder over the exact "
                "frozen document semantics, and PackageAssembler consumes that same builder. A "
                "consumer can reconstruct the persisted decision target and assertion from the "
                "selected frozen document; changing any bound document field changes the target "
                "version, so an opaque decision id alone cannot authorize the package."
            ),
            test=(
                "apps/backend/tests/reporting/test_package_document.py"
                "::test_AC_reporting_package_document_10_reconstructs_exact_decision_coordinates"
            ),
            priority="P0",
            status="done",
            proof_kind="exact",
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
                "Multi-month CSV statements with reviewed semantic dispositions parse, "
                "approve under the balance-chain guard, auto-post without an Uncategorized "
                "fallback, and tie the assembled period reports out end to end."
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
                "to the ledger only after a reviewed semantic disposition supplies its "
                "counter-account."
            ),
            # was AC8.15.2
            test=(
                "apps/backend/tests/integration/test_bank_statement_auto_account_post.py"
                "::test_AC8_15_2_bank_statement_auto_creates_account_and_posts_with_reviewed_disposition"
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
                "A source-labelled ledger input and a superseded manual valuation both reach the "
                "report correctly: the equation holds, source confidence is not presented as "
                "assurance, and the superseded valuation is excluded."
            ),
            # was AC8.16.1
            test=(
                "apps/backend/tests/integration/test_augmentation_seam_e2e.py"
                "::test_AC8_16_1_augmentation_seam_excludes_superseded_without_source_assurance"
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
        # ── group net-worth-timeseries: dashboard net-worth history endpoint
        # (was EPIC-005 AC5.7.1/AC5.7.3, #1821 Wave A pending-package move) ──
        ACRecord(
            id="AC-reporting.net-worth-timeseries.1",
            statement=(
                "GET /api/reports/net-worth/timeseries?from=YYYY-MM-DD&to=YYYY-MM-DD"
                "&granularity=monthly|daily (plus an optional 3-letter "
                "currency parameter selecting the reporting currency) returns "
                "[{date, total_assets, total_liabilities, net_worth}]."
            ),
            # was AC5.7.1
            test=(
                "apps/backend/tests/reporting/test_net_worth_timeseries.py"
                "::test_net_worth_timeseries_router"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.net-worth-timeseries.2",
            statement=(
                "Net worth time-series respects multi-currency: each point is "
                "converted to the base currency using the historical FX rate "
                "per the transaction-date rate rule."
            ),
            # was AC5.7.3
            test=(
                "apps/backend/tests/reporting/test_net_worth_timeseries.py"
                "::test_net_worth_timeseries_uses_historical_fx_per_point"
            ),
            priority="P1",
            status="done",
        ),
        # ── group portfolio-valuation-gate: brokerage portfolio value gate
        # (was EPIC-008 AC8.13.18/AC8.13.19, reporting-owned per the EPIC's own
        # migration note, #1821 Wave A pending-package move) ──
        ACRecord(
            id="AC-reporting.portfolio-valuation-gate.1",
            statement=(
                "The brokerage portfolio gate validates market valuation "
                "adjustment lines even when unrelated asset lines lower total "
                "assets (also proven at the reporting-unit level by "
                "test_portfolio_market_adjustment_survives_unrelated_negative_asset_lines "
                "in apps/backend/tests/reporting/test_reporting_net_worth_components.py)."
            ),
            # was AC8.13.18
            test=(
                "tests/e2e/test_brokerage_upload_to_portfolio_value.py"
                "::test_portfolio_valuation_gate_ignores_unrelated_negative_asset_lines"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.portfolio-valuation-gate.2",
            statement=(
                "Brokerage portfolio gate failures include holdings, valuation "
                "adjustment, non-portfolio asset, and balance-sheet "
                "diagnostics."
            ),
            # was AC8.13.19
            test=(
                "tests/e2e/test_brokerage_upload_to_portfolio_value.py"
                "::test_portfolio_valuation_gate_failure_diagnostics_are_actionable"
            ),
            priority="P0",
            status="done",
        ),
        # ── group annualized-dashboard: dashboard annualized-income/restricted
        # cards (was EPIC-011 AC11.8.1/AC11.8.3/AC11.8.7, #1821 Wave A
        # pending-package move) ──
        ACRecord(
            id="AC-reporting.annualized-dashboard.1",
            statement=(
                "GET /api/income/annualized returns {annualized_salary, "
                "annualized_bonus, annualized_dividend, annualized_total, "
                "currency, as_of} derived from the last 12 months of "
                "Income-type journal entries."
            ),
            # was AC11.8.1
            test=(
                "apps/backend/tests/reporting/test_income_annualized_router.py"
                "::test_annualized_income_endpoint_groups_last_12_month_income"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.annualized-dashboard.2",
            statement=(
                "GET /api/assets/restricted returns ESOP/RSU/locked holdings "
                "with {ticker, quantity, vesting_schedule, unlock_date, "
                "fair_value}."
            ),
            # was AC11.8.3
            test=(
                "apps/backend/tests/reporting/test_income_annualized_router.py"
                "::test_restricted_assets_endpoint_returns_latest_locked_holdings"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.annualized-dashboard.3",
            statement=(
                "GET /api/income/annualized converts mixed-currency annualized "
                "income totals into the dashboard reporting currency before "
                "aggregation."
            ),
            # was AC11.8.7
            test=(
                "apps/backend/tests/reporting/test_income_annualized_router.py"
                "::test_AC11_8_7_annualized_income_endpoint_converts_mixed_currency_totals"
            ),
            priority="P1",
            status="done",
        ),
        # ── group package-annualized: extends the existing group with the
        # report-package annualized-income schedule rows (was EPIC-011
        # AC11.11.1-4, #1821 Wave A pending-package move) ──
        ACRecord(
            id="AC-reporting.package-annualized.3",
            statement=(
                "The reporting-owned annualized section returns annualized salary, "
                "bonus, dividend, total income, currency, "
                "as-of date, and trailing-period boundaries for the personal "
                "report package."
            ),
            # was AC11.11.1
            test=(
                "apps/backend/tests/reporting/test_annualized_income_schedule.py"
                "::test_AC11_11_1_AC11_11_2_annualized_schedule_includes_income_and_restricted_treatment"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.package-annualized.4",
            statement=(
                "The schedule includes ESOP/RSU/stock-option restricted "
                "holdings with valuation basis, vesting/unlock metadata, fair "
                "value, and explicit liquid-versus-restricted net worth "
                "treatment."
            ),
            # was AC11.11.2
            test=(
                "apps/backend/tests/reporting/test_annualized_income_schedule.py"
                "::test_AC11_11_1_AC11_11_2_annualized_schedule_includes_income_and_restricted_treatment"
            ),
            priority="P0",
            status="done",
        ),
        # NOTE: was AC11.11.3 ("Annualized income and restricted fair-value
        # package totals are Decimal-safe and converted to the schedule
        # reporting currency") — duplicate of the ALREADY-migrated
        # AC-reporting.package-annualized.2 ("The annualized income package
        # schedule converts mixed-currency income and restricted totals into
        # one reporting currency", was AC5.11.3), which cites the exact same
        # test (test_AC5_11_3_AC11_11_3_annualized_schedule_converts_mixed_currency_totals)
        # and whose docstring already names both AC5.11.3 and AC11.11.3. The
        # EPIC-011 row is deleted with no new roadmap entry (#1821 Wave A).
        ACRecord(
            id="AC-reporting.package-annualized.5",
            statement=(
                "Each restricted holding's valuation_basis surfaces the "
                "snapshot's structured evidence basis enum value (or "
                "unspecified when none was captured) instead of a hardcoded "
                "source-kind literal (#706)."
            ),
            # was AC11.11.4
            test=(
                "apps/backend/tests/reporting/test_annualized_income_schedule.py"
                "::test_AC11_11_4_annualized_schedule_surfaces_structured_valuation_basis"
            ),
            priority="P0",
            status="done",
        ),
        # ── group net-worth-components: extends the existing group with the
        # unified allocation schedule (was EPIC-017 AC17.14.2, #1821 Wave A
        # pending-package move) ──
        ACRecord(
            id="AC-reporting.net-worth-components.3",
            statement=(
                "Reports expose a net-worth allocation schedule grouped by "
                "asset class, liquidity class, and source currency, with "
                "signed rows that reconcile to net worth and retain "
                "source-line drill-through metadata (endpoint contract also "
                "proven by test_AC17_14_2_net_worth_allocation_endpoint_returns_contract "
                "in apps/backend/tests/reporting/test_reports_router.py)."
            ),
            # was AC17.14.2
            test=(
                "apps/backend/tests/reporting/test_reporting_net_worth_components.py"
                "::test_AC17_14_2_net_worth_allocation_groups_balance_sheet_sources"
            ),
            priority="P1",
            status="done",
        ),
        # ── group api-vectors: backend-owned API response conformance
        # vectors (#1827 G-contract-reddens, pattern from #1167). The wire
        # shape of GET /api/reports/balance-sheet is committed as
        # common/reporting/conformance/vectors.json; the backend drift test
        # recomputes it and the frontend loads the same file as mock data. ──
        ACRecord(
            id="AC-reporting.api-vectors.1",
            statement=(
                "The serialized GET /api/reports/balance-sheet response "
                "(BalanceSheetResponse wire shape, decimal-string amounts, "
                "real fx-warning keys) recomputed from fixed deterministic "
                "inputs equals the committed "
                "common/reporting/conformance/vectors.json, so a serializer "
                "change without vector regeneration reds CI (#1827)."
            ),
            test=(
                "apps/backend/tests/schemas/test_api_response_vectors.py"
                "::test_AC_reporting_api_vectors_1_balance_sheet_matches_committed_vector"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.api-vectors.2",
            statement=(
                "The frontend balance-sheet page test consumes the committed "
                "reporting conformance vector verbatim as its mock data (via "
                "the shared fixture helper), so a regenerated breaking wire "
                "shape reds the frontend suite (#1827)."
            ),
            test=(
                "apps/frontend/src/__tests__/balanceSheetPage.test.tsx"
                "::AC16.14.2 / test_AC8_13_48 renders string totals and "
                "refetches by date"
            ),
            priority="P1",
            status="done",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-016
        # (two-stage-review-ui) ──
        ACRecord(
            id="AC-reporting.fe-report-surfaces.1",
            statement="Dashboard page shows loading state before API responses resolve",
            # was AC16.12.1
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC16.12.1 shows loading state before dashboard data resolves",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.2",
            statement="Dashboard page renders error fallback and retry action when API request fails",
            # was AC16.12.2
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC16.12.2 renders error fallback and retry action on failure",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.3",
            statement="Dashboard page renders KPI, charts, and recent activity when API requests succeed",
            # was AC16.12.3
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC16.12.3 AC22.1.2 renders KPI, chart, activity, and alert sections when API succeeds",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.4",
            statement="Dashboard page renders empty-state copy when trend or activity datasets are empty",
            # was AC16.12.4
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC16.12.4 renders empty-state messages for missing datasets",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.5",
            statement="Dashboard page renders first-time onboarding when accounts, statements, or posted review output are missing",
            # was AC16.12.17
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC22.16.1 AC16.12.17 AC16.12.18 renders first-time onboarding with everyday-surface links only",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.6",
            statement="Dashboard onboarding links users to Accounts, Statements upload, and Review in one click",
            # was AC16.12.18
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC22.16.1 AC16.12.17 AC16.12.18 renders first-time onboarding with everyday-surface links only",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.7",
            statement="Dashboard hides onboarding once an approved statement and posted journal entry exist",
            # was AC16.12.19
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC16.12.19 hides first-time onboarding after approved statement and posted journal entry exist",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.8",
            statement="Reports page renders all report cards with links for available reports",
            # was AC16.12.11
            test="apps/frontend/src/__tests__/reportsPage.test.tsx::AC16.12.11 renders the four front reports and the More reports with links",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.9",
            statement="Reports page displays accounting equation section content",
            # was AC16.12.12
            test="apps/frontend/src/__tests__/reportsPage.test.tsx::AC16.12.12 displays accounting equation section",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.10",
            statement="Balance-sheet page renders loading and error retry states",
            # was AC16.14.1
            test="apps/frontend/src/__tests__/balanceSheetPage.test.tsx::AC16.14.1 renders loading and error retry states",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.11",
            statement="Balance-sheet page renders totals and account sections on successful fetch",
            # was AC16.14.2
            test="apps/frontend/src/__tests__/balanceSheetPage.test.tsx::AC16.14.2 / test_AC8_13_48 renders string totals and refetches by date",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.12",
            statement="Balance-sheet page toggles account tree expansion controls",
            # was AC16.14.3
            test="apps/frontend/src/__tests__/balanceSheetPage.test.tsx::AC16.14.3 toggles tree expansion controls",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.13",
            statement="Income-statement page renders loading and error retry states",
            # was AC16.14.4
            test="apps/frontend/src/__tests__/incomeStatementPage.test.tsx::AC16.14.4 renders loading and error retry states",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.14",
            statement="Income-statement page renders KPI cards and category lists on success",
            # was AC16.14.5
            test="apps/frontend/src/__tests__/incomeStatementPage.test.tsx::AC16.14.5 / test_AC8_13_48 renders string KPI cards and category lists",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.15",
            statement="Income-statement page tag filters can be selected and cleared",
            # was AC16.14.6
            test="apps/frontend/src/__tests__/incomeStatementPage.test.tsx::AC16.14.6 supports selecting and clearing tags",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.16",
            statement="Cash-flow page renders loading and error retry states",
            # was AC16.14.7
            test="apps/frontend/src/__tests__/cashFlowPage.test.tsx::AC16.14.7 renders loading and error retry states",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.17",
            statement="Cash-flow page renders summary and section cards on success",
            # was AC16.14.8
            test="apps/frontend/src/__tests__/cashFlowPage.test.tsx::AC16.14.8 / test_AC8_13_48 renders string summary and activity sections",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.18",
            statement="Cash-flow page renders sankey chart when summary exists",
            # was AC16.14.9
            test="apps/frontend/src/__tests__/cashFlowPage.test.tsx::AC16.14.9 renders sankey chart when summary exists",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.19",
            statement="Bar and pie chart components render semantic labels and filtered data",
            # was AC16.19.10
            test="apps/frontend/src/__tests__/chartsComponents.test.tsx::AC16.19.10 bar chart and pie chart render labels and filtered segments",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.20",
            statement="Trend chart renders line/area paths and point labels for provided series",
            # was AC16.19.11
            test="apps/frontend/src/__tests__/chartsComponents.test.tsx::AC16.19.11 trend chart renders point labels and svg paths",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.21",
            statement="Sankey chart builds empty-state and data-state options for inflow and outflow links",
            # was AC16.21.7
            test="apps/frontend/src/__tests__/sankeyChartComponent.test.tsx::AC16.21.7 renders empty-state option when no series data is provided",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-report-surfaces.22",
            statement="Sankey chart recomputes theme-aware colors when root theme attributes change",
            # was AC16.21.8
            test="apps/frontend/src/__tests__/sankeyChartComponent.test.tsx::AC16.21.8 recomputes theme-driven colors on root attribute change",
            priority="P2",
            status="done",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-022
        # (everyday-user-ia) and EPIC-005 (reporting-visualization) ──
        ACRecord(
            id="AC-reporting.fe-viz-reports.1",
            statement="Annualized income KPI dashboard card renders the endpoint's figures (backend endpoint half migrated as `AC-reporting.kpis.1`; calculation ownership migrated to the `reporting` package roadmap as `AC-reporting.annualized-dashboard.1`, #1821 Wave A)",
            # was AC5.6.4
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC11.8.2/AC11.8.6/AC5.6.4 renders Annualized Income card with the four metric labels",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.1",
            statement="The authenticated Home renders financial key numbers, an action-required summary, and a quick-upload entry",
            # was AC22.1.2
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC16.12.3 AC22.1.2 renders KPI, chart, activity, and alert sections when API succeeds",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.2",
            statement="Personal report package renders the `investment_performance` report section from the EPIC-017 schedule API (backend contract half migrated as `AC-reporting.package-investment.1`)",
            # was AC5.8.1
            test="apps/frontend/src/__tests__/portfolioPage.test.tsx::AC5.8.1 renders investment performance report schedule from the schedule API",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.2",
            statement="The `/reports` front section renders exactly four report blocks: Balance Sheet, Income Statement, Annualized Income, and Reconciliation coverage (reconciliation match rate / unmatched count)",
            # was AC22.3.1
            test="apps/frontend/src/__tests__/reportsCockpit.test.tsx::AC22.3.1 leads with exactly the four everyday report blocks and their live figures",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.3",
            statement="Frontend personal package page renders the contract section IDs and labels from the API contract",
            # was AC5.9.3
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC5.9.3 renders personal package contract sections from API",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.3",
            statement='All other reports (Cash Flow, Personal Report Package, and any future reports) live behind a single "More" control, not the front section',
            # was AC22.3.2
            test="apps/frontend/src/__tests__/reportsCockpit.test.tsx::AC22.3.2 keeps Cash Flow and the Personal Report Package behind the More control",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.4",
            statement="Frontend/export contract surfaces stable export format and CSV columns for package consumers",
            # was AC5.9.4
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC5.9.4 renders export contract metadata",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.4",
            statement="A reusable lineage drill-down component lets a user click any amount on the Balance Sheet or Income Statement, list the contributing journal lines, and open the full evidence chain (journal line → bank statement transaction → atomic transaction → source document)",
            # was AC22.3.4
            test="apps/frontend/src/__tests__/balanceSheetDrilldown.test.tsx::AC22.3.4 lists contributing journal lines and opens the lineage chain for one",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.5",
            statement="Frontend personal package page renders annualized income totals and restricted treatment from the schedule endpoint",
            # was AC5.11.2
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC5.11.2 renders annualized income schedule values and restricted treatment",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.5",
            statement='Accounts/amounts with no contributing lines or no graph-compatible anchor degrade gracefully with an explicit empty/"no source linked" state and no crash',
            # was AC22.3.5
            test="apps/frontend/src/__tests__/balanceSheetDrilldown.test.tsx::AC22.3.5 shows an empty state when no transactions contribute",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.6",
            statement="Frontend personal package page renders notes and disclosure basis from the notes endpoint",
            # was AC5.12.3
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC5.12.3 renders package notes and disclosure basis",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.6",
            statement="Desktop and mobile smoke covers the four-block cockpit and a Balance Sheet drill-down open/close without layout overflow",
            # was AC22.3.6
            test="apps/frontend/playwright/reports-cockpit.spec.ts::${label} shows the four blocks and drills a balance-sheet amount",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.7",
            statement="Frontend personal package page renders source, ledger, review, and identifier metadata from the appendix",
            # was AC5.13.3
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC5.13.3 AC5.16.3 AC5.16.4 renders traceability appendix source, ledger, review, and identifiers",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.7",
            statement="The Home (`/`) defaults to a lean view (action-required summary, financial key numbers, quick upload) with heavy analytics/charts behind an opt-in toggle",
            # was AC22.4.4
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC22.4.4 defaults to a lean Home with heavy analytics behind an opt-in toggle",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.8",
            statement="Balance sheet page exposes the restricted-holdings include toggle and renders equation component detail (backend default-exclusion half migrated as `AC-reporting.trust-signals.1`; (AC16.14.2 removed, canonical: the same shared test also proves migrated to reporting package roadmap, #1821 Wave B))",
            # was AC5.16.1
            test="apps/frontend/src/__tests__/balanceSheetPage.test.tsx::AC16.14.2 / test_AC8_13_48 renders string totals and refetches by date",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.8",
            statement="E2E: an amount on the Balance Sheet drills down to its contributing journal lines and on to the source document",
            # was AC22.4.6
            test="apps/frontend/playwright/epic022-drilldown-journey.spec.ts::${label}: a Balance Sheet amount drills to its contributing line and on to the source document",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.9",
            statement="Balance sheet, income statement, and cash-flow report pages surface backend `fx_warnings` instead of silently rendering partial totals (backend fx_warnings-preservation half migrated as `AC-reporting.trust-signals.2`)",
            # was AC5.16.2
            test="apps/frontend/src/__tests__/balanceSheetPage.test.tsx::AC16.14.2 / test_AC8_13_48 renders string totals and refetches by date",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.9",
            statement='The Home surfaces a single primary next-action with overlapping reconciliation links de-duplicated, and the Chat page heading reads "AI Advisor"',
            # was AC22.5.6
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC22.16.2 AC22.5.6 routes the risk radar and unmatched CTA to the unified /attention queue",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.10",
            statement="Personal report package traceability renders concrete source and ledger identifiers when the appendix provides them",
            # was AC5.16.3
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC5.13.3 AC5.16.3 AC5.16.4 renders traceability appendix source, ledger, review, and identifiers",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.10",
            statement="Clicking a cash-flow amount opens the account-lineage drawer for that account's contributing journal lines (the backend account-anchor half migrated to the `reporting` package roadmap as `AC-reporting.lineage.2`, migration closeout continuation, #1663 / #1716; the frontend drawer half stays here)",
            # was AC22.7.1
            test="apps/frontend/src/__tests__/cashFlowPage.test.tsx::AC22.7.1 drills a cash-flow amount down to its account lineage",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.11",
            statement="Personal report package page exposes an authenticated CSV export action after framework selection, using the package export contract and selected framework ID",
            # was AC5.17.2
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC5.17.2 downloads package CSV through authenticated apiDownload",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.11",
            statement="The reusable lineage panel renders evidence nodes as an ordered source-to-report path with per-hop source, confidence, and version badges when those fields are available",
            # was AC22.7.2
            test="apps/frontend/src/__tests__/lineagePanel.test.tsx::AC22.7.2 renders an ordered lineage path with source, confidence, and version badges",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.12",
            statement="The package page shows recent snapshots, can generate a new snapshot, and downloads JSON/CSV from the saved snapshot artifact",
            # was AC5.19.4
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC5.19.4 generates and downloads package snapshots",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.12",
            statement="The Cash Flow statement renders a reconciliation that ties beginning cash + net cash flow to ending cash, and explicitly flags when it does not reconcile",
            # was AC22.7.3
            test="apps/frontend/src/__tests__/cashFlowPage.test.tsx::AC22.7.3 flags cash that does not tie (beginning + net != ending)",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.13",
            statement="`ReportPageShell` renders title, description, and toolbar slot, and shows the report body when not loading or errored",
            # was AC5.33.1
            test="apps/frontend/src/__tests__/reportPageShell.test.tsx::AC5.33.1 renders title, description, toolbar, and body content",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.13",
            statement="Desktop and mobile Playwright smoke covers Cash Flow amount drill-down opening the account-lineage drawer without document horizontal overflow",
            # was AC22.7.4
            test="apps/frontend/playwright/cash-flow-drilldown.spec.ts::${scenario.name} opens account-lineage drawer from a cash-flow amount",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.14",
            statement="`ReportPageShell` renders the loading skeleton (and not the body) while `isLoading`",
            # was AC5.33.2
            test="apps/frontend/src/__tests__/reportPageShell.test.tsx::AC5.33.2 shows loading skeleton while loading",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.14",
            statement="The report package titles its sections with human-readable labels (Reporting Framework, Report Readiness, Source Trust, Framework Policy, schedules, Traceability Appendix) rather than developer-facing snake_case identifiers",
            # was AC22.8.1
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC22.8.1 titles package sections with human labels, not developer snake_case identifiers",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.15",
            statement="`ReportPageShell` renders the error message with a working Retry action on `isError`",
            # was AC5.33.3
            test="apps/frontend/src/__tests__/reportPageShell.test.tsx::AC5.33.3 shows error message and retries on click",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.15",
            statement="The loaded report package starts with a readable cover sheet and table of contents that expose the package id, selected framework, report date, and linked human section titles",
            # was AC22.8.2
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC22.8.2 AC22.13.3 renders a readable package cover and linked table of contents",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.16",
            statement="`ReportToolbar` composes the AI-prompt action, Home link, and CSV export action from its props",
            # was AC5.33.4
            test="apps/frontend/src/__tests__/reportToolbar.test.tsx::AC5.33.4 renders AI prompt, home link, and caller-provided export control",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.16",
            statement="The unselected-framework and framework-package loading states reserve the package layout with guidance or skeleton placeholders, never a blank text-only pre-selection or loading screen",
            # was AC22.8.3
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC20.6.1 AC22.8.3 AC22.13.3 requires explicit framework selection before loading framework-scoped package output",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.17",
            statement="`AiPromptAction` links to the chat route with a URL-encoded prompt",
            # was AC5.33.5
            test="apps/frontend/src/__tests__/reportToolbar.test.tsx::AC5.33.5 links to chat with url-encoded prompt",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.17",
            statement="Desktop and mobile Playwright smoke covers report-package framework selection, cover, table of contents, readiness, and no document horizontal overflow",
            # was AC22.8.4
            test="apps/frontend/playwright/report-readiness.spec.ts::${scenario.name} renders cover, contents, and readiness before package output",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.18",
            statement="`DateFilterControl` renders a labelled date input and emits changes",
            # was AC5.34.1
            test="apps/frontend/src/__tests__/reportFilters.test.tsx::AC5.34.1 renders labelled date input and emits change",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.18",
            statement="The Reports cockpit's reconciliation-coverage block stays in the reports context and does not link into the Advanced `/reconciliation` surface",
            # was AC22.9.1
            test="apps/frontend/src/__tests__/reportsCockpit.test.tsx::AC22.9.1 keeps the reconciliation-coverage block in the reports context, not linked into Advanced",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.19",
            statement="`CurrencyFilterControl` renders a labelled currency select with the provided options and emits changes",
            # was AC5.34.2
            test="apps/frontend/src/__tests__/reportFilters.test.tsx::AC5.34.2 renders currency options and emits change",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.19",
            statement='The "Annualized Income" cockpit card\'s destination matches its label (it opens the report package and the caption says so), with no silent label/destination mismatch',
            # was AC22.9.3
            test="apps/frontend/src/__tests__/reportsCockpit.test.tsx::AC22.9.3 makes the Annualized Income card's destination match its label",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.20",
            statement="`useReportFilters` builds a query string from its date and currency state",
            # was AC5.34.3
            test="apps/frontend/src/__tests__/useReportFilters.test.ts::AC5.34.3 builds query string from filter state",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.20",
            statement="The Home getting-started steps link only to everyday surfaces — the first step targets `/upload` and no step links to the accounting-jargon `/accounts` route",
            # was AC22.16.1
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC22.16.1 AC16.12.17 AC16.12.18 renders first-time onboarding with everyday-surface links only",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.21",
            statement="`useReportFilters` derives the CSV export path for the given report type",
            # was AC5.34.4
            test="apps/frontend/src/__tests__/useReportFilters.test.ts::AC5.34.4 derives csv export path for report type",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.21",
            statement='The Home presents a single confidence-ranked attention entry point: the analytics reconciliation ("Risk radar") card and the unmatched-alerts call-to-action link to the unified `/attention` queue instead of parallel Advanced reconciliation internals (`/reconciliation`, `/reconciliation/unmatched`, `/review`)',
            # was AC22.16.2
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC22.16.2 AC22.5.6 routes the risk radar and unmatched CTA to the unified /attention queue",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.22",
            statement="`useReportFilters` updates the query string when the currency changes",
            # was AC5.34.5
            test="apps/frontend/src/__tests__/useReportFilters.test.ts::AC5.34.5 updates query string when currency changes",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.22",
            statement="`useDashboardData` is composed from independently-usable hooks (`useDashboardSnapshot` for the financial/reconciliation aggregate and `useAssetTrend` for the per-account trend), each callable on its own through the shared `apiFetch` transport, while the aggregate hook preserves its existing public result contract",
            # was AC22.16.3
            test="apps/frontend/src/__tests__/useDashboardData.test.ts::AC22.16.3 composes the snapshot and asset-trend hooks, exposing the trend once the balance loads",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.23",
            statement="`useReportFilters` seeds its initial date/currency state from the URL query params (`as_of_date`/`start_date`/`end_date`/`currency`) with precedence explicit option > URL param > default, so report routes honour deep links",
            # was AC5.34.6
            test="apps/frontend/src/__tests__/useReportFilters.test.ts::AC5.34.6 seeds initial filter state from URL query params",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.23",
            statement="The loaded report package uses reader-facing labels for evidence coverage, reporting basis, and traceability summary, with proof-system labels such as `Deterministic PR`, `Post-merge LLM/OCR`, `Framework Policy`, raw gap codes, raw blocker codes, and policy result IDs kept out of the primary visible layer",
            # was AC22.19.1
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC22.19.1 renders the loaded package with reader-first labels before proof internals",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.24",
            statement="`useDashboardData` aggregates the dashboard endpoints over `apiFetch` and exposes a single loading flag",
            # was AC5.35.1
            test="apps/frontend/src/__tests__/useDashboardData.test.ts::AC5.35.1 aggregates dashboard endpoints over apiFetch",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.24",
            statement="Explicit `Audit details` disclosures keep the same source-trust, framework-policy, traceability, blocker, matrix-version, line-id, confidence, review-state, and evidence-reference details keyboard reachable and screen-reader comprehensible",
            # was AC22.19.2
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC22.19.2 keeps proof and policy internals in keyboard-reachable audit details",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.25",
            statement="`useDashboardData` normalizes missing balance-sheet / income / annualized fields to safe decimal-string defaults",
            # was AC5.35.2
            test="apps/frontend/src/__tests__/useDashboardData.test.ts::AC5.35.2 normalizes missing report fields to defaults",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.25",
            statement="Print/save and export metadata default to the reader-first hierarchy; raw CSV columns, policy result IDs, matrix version, and evidence bundle references are available only in an explicit audit/export-details disclosure",
            # was AC22.19.3
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC22.19.3 keeps export proof metadata behind a print-hidden export audit disclosure",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.26",
            statement="`useDashboardData` surfaces an error message and a retry that refetches when aggregation fails",
            # was AC5.35.3
            test="apps/frontend/src/__tests__/useDashboardData.test.ts::AC5.35.3 surfaces error and retries on failure",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-ia-reports.26",
            statement="The Home renders the net-worth headline, a three-statement segmented entry (Balance Sheet / Income / Cash Flow) each deep-linking to its full report, the single next-action, the attention bell, and keeps heavy charts behind an opt-in toggle",
            # was AC22.21.6
            test="apps/frontend/src/__tests__/homeStatements.test.tsx::deep-links each of the three statements to its full report",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.27",
            statement="`useDashboardData` tolerates a failing chat-suggestions endpoint without failing the whole dashboard",
            # was AC5.35.4
            test="apps/frontend/src/__tests__/useDashboardData.test.ts::AC5.35.4 tolerates failing chat suggestions endpoint",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.28",
            statement="Net worth chart component on dashboard renders ECharts line chart with date X-axis and net-worth Y-axis",
            # was AC5.7.2
            test="apps/frontend/src/__tests__/uiGapAudit.netWorthTimeSeries.test.tsx::AC5.7.2/AC5.7.6 mounts an ECharts-backed net worth line chart",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.29",
            statement="Time range selector (1M / 3M / 6M / 1Y / All) on dashboard toggles `from` parameter for chart",
            # was AC5.7.4
            test="apps/frontend/src/__tests__/uiGapAudit.netWorthTimeSeries.test.tsx::AC5.7.4 range selector toggles the from parameter and re-fetches",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.30",
            statement="Empty-state placeholder rendered when fewer than 2 data points exist (cannot draw line)",
            # was AC5.7.5
            test="apps/frontend/src/__tests__/uiGapAudit.netWorthTimeSeries.test.tsx::AC5.7.5 renders an empty state when fewer than two points exist",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.31",
            statement="Frontend unit test mounts NetWorthTimeSeries component and asserts chart container exists",
            # was AC5.7.6
            test="apps/frontend/src/__tests__/uiGapAudit.netWorthTimeSeries.test.tsx::AC5.7.2/AC5.7.6 mounts an ECharts-backed net worth line chart",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.32",
            statement="The Reports cockpit renders package readiness state, blocker count, next action, and source-gap summary before report cards",
            # was AC5.37.1
            test="apps/frontend/src/__tests__/reportsCockpit.test.tsx::AC5.37.1 renders trust-first readiness before report cards",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-viz-reports.33",
            statement=(
                "If readiness loading fails, the Reports cockpit shows a "
                "contained unavailable state while preserving report navigation."
            ),
            # was AC5.37.2
            test="apps/frontend/src/__tests__/reportsCockpit.test.tsx::AC5.37.2 preserves report navigation when readiness is unavailable",
            priority="P1",
            status="done",
            vision_anchor="non-goals-not-budgeting-app",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from the
        # remaining EPIC files (EPIC-001/002/004/008/011/012/015/017/018/019/021/024/025) ──
        ACRecord(
            id="AC-reporting.fe-remainder-reports.1",
            statement="The report package traceability surface exposes a lineage panel from at least one report traceability row",
            # was AC18.9.4
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC18.9.4 AC18.9.5 AC18.9.6 opens an Evidence Graph lineage panel from report traceability",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-remainder-reports.2",
            statement="The lineage panel renders source document, extracted record, atomic fact, ledger entry, ledger line, and report-line anchors when present",
            # was AC18.9.5
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC18.9.4 AC18.9.5 AC18.9.6 opens an Evidence Graph lineage panel from report traceability",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-remainder-reports.3",
            statement="Tests cover report line to source document navigation and source document to impacted ledger/report navigation",
            # was AC18.9.6
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC18.9.4 AC18.9.5 AC18.9.6 opens an Evidence Graph lineage panel from report traceability",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-remainder-reports.4",
            statement="Dashboard status feed renders primary state, report readiness, recent automation, blocker/action severity, and an empty no-action state without raw audit-log noise",
            # was AC19.3.6
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC19.3.6 renders the workflow status feed on the dashboard landing surface",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-remainder-reports.5",
            statement="The first dashboard viewport renders the upload-to-report workflow home before KPI, chart, and activity content",
            # was AC19.4.2
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC19.4.2 AC16.16.1 renders the upload-to-report home before secondary dashboard metrics",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-remainder-reports.6",
            statement="The dashboard primary CTA follows `workflow.status.next_action.href` and labels upload as the default action when no higher-priority blocker/action exists",
            # was AC19.4.3
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC19.4.3 follows workflow next_action for blocker and upload primary CTAs",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-remainder-reports.7",
            statement="Report readiness state and blocker count are visible above secondary dashboard metrics and link to the readiness/report action path",
            # was AC19.4.4
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC19.4.4 renders report readiness above analytics with blocker count and link",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-remainder-reports.8",
            statement="Recent workflow events are visible, grouped by actionability, and routine automation is summarized without dominating the page",
            # was AC19.4.5
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC19.4.5 shows actionable recent events and summarizes routine automation",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-remainder-reports.9",
            statement="Secondary dashboard metric API failure does not hide the workflow home; the analytics section renders an isolated retry/error state",
            # was AC19.4.6
            test="apps/frontend/src/__tests__/dashboardPage.test.tsx::AC19.4.6 keeps upload-to-report home visible when secondary analytics fail",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-remainder-reports.10",
            statement="Desktop and mobile Playwright smoke covers the upload-first dashboard entry without layout overflow",
            # was AC19.4.7
            test="apps/frontend/playwright/upload-first-dashboard.spec.ts::${scenario.name} renders upload-to-report home before secondary analytics",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-remainder-reports.11",
            statement="Personal report package page renders readiness state and blocker links before package section output",
            # was AC19.5.4
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC19.5.4 renders package readiness before report package output",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-remainder-reports.12",
            statement="Personal report package page renders non-blocked readiness states without stale blocker cards",
            # was AC19.5.5
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC19.5.5 renders non-blocked readiness states without blocker cards",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-remainder-reports.13",
            statement="Report readiness has route-level Playwright smoke coverage before package output",
            # was AC19.8.7
            test="apps/frontend/playwright/report-readiness.spec.ts::${scenario.name} renders cover, contents, and readiness before package output",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.fe-remainder-reports.14",
            statement="Personal report package page renders decision authority coverage before detailed traceability output",
            # was AC19.9.2
            test="apps/frontend/src/__tests__/personalReportPackagePage.test.tsx::AC19.9.2 renders decision authority coverage before traceability details",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reporting.cash-events.1",
            statement="Only journal entries touching an exact cash identity can produce cash-flow activity; non-cash accruals and financed asset acquisitions produce none.",
            test="apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_1_2_only_cash_touch_events_are_classified",
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.cash-events.2",
            statement="Cash events are classified from their non-cash counterpart accounts, and later cash settlement is recognized independently from the original accrual.",
            test="apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_1_2_only_cash_touch_events_are_classified",
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.cash-events.3",
            statement="Direct and Processing-mediated internal transfers among cash and cash-equivalent identities emit no operating, investing, or financing activity.",
            test="apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_3_4_internal_transfers_are_neutral_and_bridge_ties",
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.cash-events.4",
            statement="The cash bridge separately discloses classified activity, unclassified cash, and FX effect and proves that they equal ending cash less beginning cash.",
            test="apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_3_4_internal_transfers_are_neutral_and_bridge_ties",
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.cash-events.5",
            statement="Every cash-event query predicates both JournalEntry.user_id and Account.user_id and rejects an entry containing any foreign-tenant account line.",
            test="apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_5_dual_tenant_predicates_reject_hostile_entries",
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.cash-events.6",
            statement="generate_cash_flow is the single reporting-owned cash projection used by standalone and package consumers.",
            test="apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_6_7_one_projection_serves_proven_and_unproven_consumers",
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.cash-events.7",
            statement="Exact cash identities produce proven output while standalone lexical discovery is explicitly unproven and cannot authorize a package.",
            test="apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_6_7_one_projection_serves_proven_and_unproven_consumers",
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.cash-events.8",
            statement="Each classified cash event exposes its exact journal-entry and journal-line evidence anchors.",
            test="apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_8_10_lineage_void_and_ambiguous_events_fail_closed",
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
        ACRecord(
            id="AC-reporting.cash-events.9",
            statement="Package governance detail projects the exact detector, proof strength, target SHA, issue, and existing enforcing gate for every cash-event guarantee.",
            test="apps/backend/tests/reporting/test_cash_event_projection.py::test_AC_reporting_cash_events_9_governance_detail_is_package_owned_and_enforced",
            priority="P0",
            status="done",
            proof_kind="exact",
        ),
    ],
    governance=[
        GovernanceInitiative(
            id="authoritative-cash-event-projection",
            title="Tenant-safe authoritative cash-event projection",
            issue="https://github.com/wangzitian0/finance_report/issues/1971",
            depends_on=["meta/governance-control-plane"],
            guarantees=[
                GovernanceGuarantee(
                    id="cash-touch-only",
                    statement="Only cash-touch journal events emit cash-flow activity.",
                    affected_acs=["AC-reporting.cash-events.1"],
                    detector="non-cash-events-in-cash-flow",
                    target="0 non-cash events",
                    lock="ci.backend_integration",
                    proof="cash-event-adversarial-oracle",
                    required_proof_strength="value-oracle",
                    enforcing_gate="ci.backend_integration",
                ),
                GovernanceGuarantee(
                    id="event-classification",
                    statement="Cash events classify from exact non-cash counterparts.",
                    affected_acs=["AC-reporting.cash-events.2"],
                    detector="account-period-inference-paths",
                    target="0 account-period inference paths",
                    lock="ci.backend_integration",
                    proof="cash-event-classification-oracle",
                    required_proof_strength="value-oracle",
                    enforcing_gate="ci.backend_integration",
                ),
                GovernanceGuarantee(
                    id="transfer-neutrality",
                    statement="Internal cash transfers emit zero activity.",
                    affected_acs=["AC-reporting.cash-events.3"],
                    detector="internal-transfer-activity-lines",
                    target="0 internal-transfer activity lines",
                    lock="ci.backend_integration",
                    proof="cash-event-transfer-neutrality",
                    required_proof_strength="value-oracle",
                    enforcing_gate="ci.backend_integration",
                ),
                GovernanceGuarantee(
                    id="cash-bridge",
                    statement="The disclosed cash bridge ties exactly.",
                    affected_acs=["AC-reporting.cash-events.4"],
                    detector="cash-bridge-deltas",
                    target="0 unreconciled bridges",
                    lock="ci.backend_integration",
                    proof="cash-event-bridge-oracle",
                    required_proof_strength="value-oracle",
                    enforcing_gate="ci.backend_integration",
                ),
                GovernanceGuarantee(
                    id="dual-tenant-isolation",
                    statement="Cash events require both entry and account tenant ownership.",
                    affected_acs=["AC-reporting.cash-events.5"],
                    detector="single-sided-cash-tenant-predicates",
                    target="0 single-sided predicates",
                    lock="ci.backend_integration",
                    proof="cash-event-hostile-tenant-fixture",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend_integration",
                ),
                GovernanceGuarantee(
                    id="one-projection-owner",
                    statement="One reporting projection serves every cash-flow consumer.",
                    affected_acs=["AC-reporting.cash-events.6"],
                    detector="parallel-cash-projection-owners",
                    target="1 projection owner",
                    lock="ci.lint",
                    proof="cash-event-consumer-contract",
                    required_proof_strength="exact",
                    enforcing_gate="ci.lint",
                ),
                GovernanceGuarantee(
                    id="consumer-proof-state",
                    statement="Consumers receive proven output or an explicit unproven state.",
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
                    statement="Every classified cash event exposes exact ledger anchors.",
                    affected_acs=["AC-reporting.cash-events.8"],
                    detector="cash-events-without-lineage",
                    target="0 unanchored classified events",
                    lock="ci.backend_integration",
                    proof="cash-event-lineage-oracle",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend_integration",
                ),
                GovernanceGuarantee(
                    id="exact-governance-detail",
                    statement="Control-plane detail exposes current proof and enforcement facts.",
                    affected_acs=["AC-reporting.cash-events.9"],
                    detector="cash-event-governance-join-gaps",
                    target="0 missing detail facts",
                    lock="ci.lint",
                    proof="governance-detail-lossless-projection",
                    required_proof_strength="exact",
                    enforcing_gate="ci.lint",
                ),
                GovernanceGuarantee(
                    id="counterfactual-lock",
                    statement="The adversarial cash-event matrix remains executable and blocking.",
                    affected_acs=[
                        "AC-reporting.cash-events.1",
                        "AC-reporting.cash-events.2",
                        "AC-reporting.cash-events.3",
                        "AC-reporting.cash-events.4",
                        "AC-reporting.cash-events.5",
                        "AC-reporting.cash-events.7",
                        "AC-reporting.cash-events.8",
                    ],
                    detector="missing-cash-event-counterfactuals",
                    target="0 missing counterfactuals",
                    lock="ci.backend_integration",
                    proof="cash-event-counterfactual-matrix",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend_integration",
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
        ),
    ],
)
