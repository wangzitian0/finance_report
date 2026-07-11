"""The ``testing`` package's machine-checkable :class:`PackageContract`.

``testing`` is an ``infra`` leaf (L1): test/fixture-scoped capability code reused
across backend, tooling, and E2E tests (mirrors ``base_values.py``'s own
docstring: "these helpers are intentionally test/fixture scoped"). It has no
production runtime edge — nothing under ``apps/*/src`` imports it — so unlike
``money``/``counter`` its BE implementation is itself: ``implementations["be"]
= "common/testing"`` (the same self-hosting shape as ``common/meta`` and the
draft ``common/runtime``).

This formalizes what was already a de facto package (50+ test files import
``common.testing.*``) with a machine-checked contract, per the package-model
cutover. It is the landing package for cassette/PDF-fixture test assets: the
32-case LLM cassette corpus (``fixtures/llm_cassettes/`` +
``fixtures/cassette-eval-baseline.jsonl``, ``Cassette`` value object) and the
PDF fixture generator + committed synthetic PDFs (``fixtures/pdf/``,
``FixtureDocument`` value object), both relocated here from
``apps/backend/tests/fixtures/`` / ``tools/_lib/pdf_fixtures/`` and
``docs/ssot/pdf-fixtures.md`` (see ``README.md#pdf-fixtures``).

The package's ACs live here in ``roadmap`` (the package-model AC registry);
``common/meta/extension/generate_ac_registry.py`` sources them directly from this
contract, same as ``counter``. ``roadmap`` groups 1-8 migrated from EPIC-009
(PDF fixture generation, the leading "9" dropped, group/seq preserved:
``AC9.<g>.<s>`` -> ``AC-testing.<g>.<s>``).

EPIC-023's cassette-layer ACs (AC23.5/AC23.6/AC23.7, plus the graded-eval
AC23.8) deliberately do NOT migrate here, even though AC23.5-.7 carry a
``{tier:CODE-ONLY}`` annotation in EPIC-023 prose: this package's own
governance gate (``common/meta/extension/check_authority_reconcile.py``) DETECTS a
package's tier from what its roadmap-AC tests actually exercise, and
``common/meta/extension/authority_classifier.py`` classifies *any* test that
drives the cassette/replay harness as the ``LLM`` band by design (the
harness is inherently LLM-facing infrastructure, not domain-agnostic testing
capability, no matter how deterministic/mocked its assertions are). A
CODE-ONLY package permits zero detected-LLM roadmap-AC tests, so cassette
tests can never be roadmap members here regardless of their EPIC-authored
tier annotation — only the relocated cassette *fixture data*
(``fixtures/llm_cassettes/``) lives in this package; the cassette
*mechanism*'s ACs (and its eventual formal home) stay with ``llm``.
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
    name="testing",
    status="active",
    # Deterministic test/fixture helpers, no LLM in the package: CODE-ONLY.
    tier="CODE-ONLY",
    # L1 is business-agnostic: no edge into the L2 value language. money's
    # conformance machinery is discovered at tool-time, not imported (the
    # common.audit.money import in base_values.py reaches the Shared-Kernel
    # canonical mirror, not the registered `audit` package's own BE
    # implementation — a different prefix, so it resolves outside this edge).
    # `meta` IS a real, declared edge: generate_ac_registry.py/contract.py
    # import common.meta.* for the AC-registry schema (#1674 made this visible
    # — it was a dark edge before the scan learned to recognise common.<pkg>
    # imports, not just src.<pkg>).
    depends_on=["meta"],
    roles=[],
    # No base/extension split yet, so these are taxonomy-only (no module path;
    # the gate skips placement for units with no module, same as money's VOs).
    units=[
        Unit(name="Cassette", kind=Kind.VALUE_OBJECT),
        Unit(name="FixtureDocument", kind=Kind.VALUE_OBJECT),
    ],
    implementations={"be": "common/testing", "fe": None},
    interface=["money_amount"],
    events=[],
    invariants=[
        Invariant(
            id="passes-own-governance-gate",
            statement="check_package_contract validates testing with no violations.",
            test=(
                "tests/tooling/test_testing_package.py"
                "::test_AC_testing_1_1_package_contract_gate_passes_for_testing"
            ),
        ),
        # ── coverage tooling folded in (was the `coverage` package) ──
        Invariant(
            id="registered-source-missing-from-lcov-fails",
            statement="The coverage policy fails when a registered source file is missing from the lcov report, so uncovered source is never silently dropped.",
            test="tests/tooling/test_coverage_policy.py::test_compare_component_fails_when_source_file_is_missing_from_lcov",
        ),
        Invariant(
            id="source-set-recursive-with-exclusions",
            statement="The expected coverage source set recursively includes all eligible files except the declared exclusions.",
            test="tests/tooling/test_coverage_policy.py::test_expected_sources_recursively_include_all_eligible_files_except_exclusions",
        ),
    ],
    roadmap=[
        # ── Group 1-8: migrated from EPIC-009 (PDF fixture generation) ──
        ACRecord(
            id="AC-testing.1.1",
            statement=("PDF analyzer exists (Was EPIC-009 AC9.1.1)."),
            test="tests/tooling/test_pdf_fixture_tooling_coverage.py::test_AC9_1_1_analyzer_extracts_page_table_and_text_positions",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.1.2",
            statement=("Template extractor exists (Was EPIC-009 AC9.1.2)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_1_2_template_extractor_writes_sanitized_format_yaml",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.1.3",
            statement=("CLI tool exists (Was EPIC-009 AC9.1.3)."),
            test="tests/tooling/test_pdf_fixture_tooling_coverage.py::test_AC9_1_3_template_extractor_emits_source_table_schema",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.1.4",
            statement=("DBS template exists (Was EPIC-009 AC9.1.4)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_1_4_AC9_1_5_AC9_1_6_committed_templates_define_source_schemas",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.1.5",
            statement=("CMB template exists (Was EPIC-009 AC9.1.5)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_1_4_AC9_1_5_AC9_1_6_committed_templates_define_source_schemas",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.1.6",
            statement=("Mari Bank template exists (Was EPIC-009 AC9.1.6)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_1_4_AC9_1_5_AC9_1_6_committed_templates_define_source_schemas",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.2.1",
            statement=("Base generator class exists (Was EPIC-009 AC9.2.1)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_2_1_base_generator_loads_template_and_applies_layout",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.2.2",
            statement=("DBS generator exists (Was EPIC-009 AC9.2.2)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_2_2_AC9_2_3_AC9_2_4_generators_load_committed_templates",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.2.3",
            statement=("CMB generator exists (Was EPIC-009 AC9.2.3)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_2_2_AC9_2_3_AC9_2_4_generators_load_committed_templates",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.2.4",
            statement=("Mari Bank generator exists (Was EPIC-009 AC9.2.4)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_2_2_AC9_2_3_AC9_2_4_generators_load_committed_templates",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.2.5",
            statement=("Font utilities exist (Was EPIC-009 AC9.2.5)."),
            test="tests/tooling/test_pdf_fixture_tooling_coverage.py::test_AC9_2_5_font_helpers_choose_safe_fonts",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.2.6",
            statement=("Fake data generator exists (Was EPIC-009 AC9.2.6)."),
            test="tests/tooling/test_pdf_fixture_tooling_coverage.py::test_AC9_2_6_fake_data_generators_keep_running_balances",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.2.7",
            statement=("Main script exists (Was EPIC-009 AC9.2.7)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_2_7_main_script_registers_all_supported_generators",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.3.1",
            statement=("Format validator exists (Was EPIC-009 AC9.3.1)."),
            test="tests/tooling/test_pdf_fixture_tooling_coverage.py::test_AC9_3_1_validator_reports_page_table_and_key_phrase_findings",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.3.2",
            statement=("Generated DBS PDF parseable (Was EPIC-009 AC9.3.2)."),
            test="tests/tooling/test_pdf_fixture_parseable.py::test_ac9_3_2_dbs_generated_pdf_parseable",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.3.3",
            statement=("Generated CMB PDF parseable (Was EPIC-009 AC9.3.3)."),
            test="tests/tooling/test_pdf_fixture_parseable.py::test_ac9_3_3_cmb_generated_pdf_parseable",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.3.4",
            statement=("Generated Mari PDF parseable (Was EPIC-009 AC9.3.4)."),
            test="tests/tooling/test_pdf_fixture_parseable.py::test_ac9_3_4_mari_generated_pdf_parseable",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.3.5",
            statement=("Balance calculations correct (Was EPIC-009 AC9.3.5)."),
            test="tests/tooling/test_pdf_fixture_parseable.py::test_ac9_3_5_balance_calculations_correct",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.3.6",
            statement=("Date formats correct (Was EPIC-009 AC9.3.6)."),
            test="tests/tooling/test_pdf_fixture_parseable.py::test_ac9_3_6_date_formats_correct_per_source",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.4.1",
            statement=("Format analysis README (Was EPIC-009 AC9.4.1)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_4_readmes_document_analysis_generation_templates_and_examples",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.4.2",
            statement=("Generation README (Was EPIC-009 AC9.4.2)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_4_readmes_document_analysis_generation_templates_and_examples",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.4.3",
            statement=("Template format specification (Was EPIC-009 AC9.4.3)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_4_readmes_document_analysis_generation_templates_and_examples",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.4.4",
            statement=("Usage examples (Was EPIC-009 AC9.4.4)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_4_readmes_document_analysis_generation_templates_and_examples",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.5.1",
            statement=(".gitignore excludes real PDFs (Was EPIC-009 AC9.5.1)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_5_git_contract_tracks_safe_sources_only",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.5.2",
            statement=("Format templates committed (Was EPIC-009 AC9.5.2)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_5_git_contract_tracks_safe_sources_only",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.5.3",
            statement=("Generators committed (Was EPIC-009 AC9.5.3)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_5_git_contract_tracks_safe_sources_only",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.5.4",
            statement=("Analyzers committed (Was EPIC-009 AC9.5.4)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_5_git_contract_tracks_safe_sources_only",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.5.5",
            statement=("Validators committed (Was EPIC-009 AC9.5.5)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_5_git_contract_tracks_safe_sources_only",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.6.1",
            statement=("DBS generator loads template (Was EPIC-009 AC9.6.1)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_6_1_AC9_6_2_generators_preserve_template_source_identity",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.6.2",
            statement=("CMB generator loads template (Was EPIC-009 AC9.6.2)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_6_1_AC9_6_2_generators_preserve_template_source_identity",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.6.3",
            statement=("CMB generator supports Chinese fonts (Was EPIC-009 AC9.6.3)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_6_3_cmb_generator_uses_registered_chinese_font",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.6.4",
            statement=(
                "Mari generator generates interest section (Was EPIC-009 AC9.6.4)."
            ),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_6_4_mari_generator_renders_interest_details_section",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.6.5",
            statement=("Generators use fictional data (Was EPIC-009 AC9.6.5)."),
            test="tests/tooling/test_pdf_fixture_epic009_behavior.py::test_AC9_6_5_generators_use_masked_accounts_and_fictional_data",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.7.1",
            statement=(
                "Main script supports --source parameter (Was EPIC-009 AC9.7.1)."
            ),
            test="tests/tooling/test_pdf_fixture_tooling_coverage.py::test_AC9_7_1_AC9_7_2_main_generates_selected_source",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.7.2",
            statement=(
                "Main script supports --output parameter (Was EPIC-009 AC9.7.2)."
            ),
            test="tests/tooling/test_pdf_fixture_tooling_coverage.py::test_AC9_7_1_AC9_7_2_main_generates_all_sources_with_default_output",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.7.3",
            statement=("Analyzer CLI supports input/output (Was EPIC-009 AC9.7.3)."),
            test="tests/tooling/test_pdf_fixture_tooling_coverage.py::test_AC9_1_3_analyzer_cli_writes_template_yaml",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.8.1",
            statement=(
                "Committed templates define sanitized real-format contracts for page, "
                "table, date, currency, and key text metadata (Was EPIC-009 AC9.8.1)."
            ),
            test="tests/tooling/test_pdf_fixture_real_format_contract.py::test_AC9_8_1_templates_define_sanitized_real_format_contract",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.8.2",
            statement=(
                "Validator rejects missing or drifting real-format contracts (Was EPIC-009 AC9.8.2)."
            ),
            test="tests/tooling/test_pdf_fixture_real_format_contract.py::test_AC9_8_2_validator_rejects_missing_or_drifting_real_format_contract",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.8.3",
            statement=(
                "Generated PDFs satisfy the real-format contract for parser-visible "
                "page, table, date, currency, and key-text structure (Was EPIC-009 AC9.8.3)."
            ),
            test="tests/tooling/test_pdf_fixture_real_format_contract.py::test_AC9_8_3_generated_pdf_matches_template_real_format_contract",
            priority="P2",
            status="done",
        ),
        # ── group journeys: core E2E journey rollup (was EPIC-008
        # AC8.8), migration closeout, #1663 / #1718 ──
        ACRecord(
            id="AC-testing.journeys.1",
            statement="API health check (Was EPIC-008 AC8.8.1).",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_api_health_check",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.journeys.2",
            statement="Accounts CRUD API (Was EPIC-008 AC8.8.2).",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_accounts_crud_api",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.journeys.3",
            statement="Journal entry lifecycle API (Was EPIC-008 AC8.8.3).",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_journal_entry_crud"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.journeys.4",
            statement="Reports API (Was EPIC-008 AC8.8.4).",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_balance_sheet_report"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.journeys.5",
            statement="Reconciliation API (Was EPIC-008 AC8.8.5).",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_reconciliation_engine_runs"
            ),
            priority="P0",
            status="done",
        ),
        # ── group ci-integration: CI/CD integration journey gates (was
        # EPIC-008 AC8.9), migration closeout, #1663 / #1718 ──
        ACRecord(
            id="AC-testing.ci-integration.1",
            statement="PR workflow runs E2E tests (Was EPIC-008 AC8.9.1).",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_pr_workflow_runs_e2e_tests"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.ci-integration.2",
            statement="Smoke tests integrated (Was EPIC-008 AC8.9.2).",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_smoke_tests_integrated"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.ci-integration.3",
            statement="Critical test check (Was EPIC-008 AC8.9.3).",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_critical_test_check_in_workflow"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.ci-integration.4",
            statement="Environment isolation (Was EPIC-008 AC8.9.4).",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_environment_isolation"
            ),
            priority="P0",
            status="done",
        ),
        # ── group must-have: must-have scenario traceability (was
        # EPIC-008 AC8.10), migration closeout, #1663 / #1718 ──
        ACRecord(
            id="AC-testing.must-have.1",
            statement="Health endpoint reachable (Was EPIC-008 AC8.10.1).",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_traceability_health_endpoint"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.must-have.2",
            statement="User can create account (Was EPIC-008 AC8.10.2).",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_traceability_user_can_create_account"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.must-have.3",
            statement="User can create journal entry (Was EPIC-008 AC8.10.3).",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_traceability_user_can_create_journal_entry"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.must-have.4",
            statement="Statement upload triggers AI (Was EPIC-008 AC8.10.4).",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_statement_upload_csv"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.must-have.5",
            statement="Reconciliation engine runs (Was EPIC-008 AC8.10.5).",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_traceability_reconciliation_engine"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.must-have.6",
            statement="Unbalanced entry rejected (Was EPIC-008 AC8.10.6).",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_traceability_unbalanced_entry_rejected"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.must-have.7",
            statement="Reports API accessible (Was EPIC-008 AC8.10.7).",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_traceability_reports_api"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.must-have.8",
            statement="User registration flow (Was EPIC-008 AC8.10.8).",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_traceability_user_registration"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.must-have.9",
            statement="Authentication validation (Was EPIC-008 AC8.10.9).",
            test=(
                "apps/backend/tests/e2e/test_core_journeys.py"
                "::test_traceability_authentication_validation"
            ),
            priority="P0",
            status="done",
        ),
        # ── group trust-mirrors: product trust proof mirrors (was
        # EPIC-008 AC8.14), migration closeout, #1663 / #1718 ──
        ACRecord(
            id="AC-testing.trust-mirrors.1",
            statement=(
                "Critical proof matrix classifies product proof paths by trust mode "
                "and source classes (Was EPIC-008 AC8.14.1)."
            ),
            test=(
                "tests/tooling/test_check_critical_proof_matrix.py"
                "::test_valid_behavioral_static_and_manual_entries_pass"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.trust-mirrors.2",
            statement=(
                "Critical post-merge LLM/OCR product proofs must name a PR "
                "deterministic mirror proof for the same source classes (Was EPIC-008 "
                "AC8.14.2)."
            ),
            test=(
                "tests/tooling/test_check_critical_proof_matrix.py"
                "::test_AC8_14_2_llm_ocr_proof_requires_deterministic_pr_mirror"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.trust-mirrors.3",
            statement=(
                "Personal report package critical proof has a deterministic PR mirror "
                "covering bank, brokerage, manual valuation, restricted-compensation, "
                "CSV, and manual-record source classes (Was EPIC-008 AC8.14.3)."
            ),
            test=(
                "tests/tooling/test_personal_report_package_fixture_contract.py"
                "::test_AC8_14_3_personal_package_has_deterministic_source_trust_mirror"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.trust-mirrors.4",
            statement=(
                "Backend reporting integration acts as a deterministic PR mirror from "
                "structured/manual source facts through ledger and core statements "
                "(Was EPIC-008 AC8.14.4)."
            ),
            test=(
                "apps/backend/tests/integration/test_reporting_e2e.py"
                "::test_AC5_15_1_multicurrency_reporting_cycle_reconciles_bs_is_cf"
            ),
            priority="P0",
            status="done",
        ),
        # ── group tier2: Tier 2 deployed HTTP E2E proof semantics (was
        # EPIC-008 AC8.18), migration closeout, #1663 / #1718 ──
        ACRecord(
            id="AC-testing.tier2.1",
            statement=(
                "The Tier 2 command fails closed unless a deployed base URL and "
                "expected deployed version are supplied (Was EPIC-008 AC8.18.1)."
            ),
            test=(
                "tests/tooling/test_tier2_http_e2e.py"
                "::test_AC8_18_1_tier2_http_command_fails_closed_without_deployed_inputs"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.tier2.2",
            statement=(
                "Tier 2 reports carry proof_tier=tier2_http; advisory/env-gated "
                "not-run output is marked proof_eligible=false, while passing reports "
                "require concrete HTTP checks (Was EPIC-008 AC8.18.2)."
            ),
            test=(
                "tests/tooling/test_tier2_http_e2e.py"
                "::test_AC8_18_2_tier2_http_report_is_proof_tiered_and_skip_ineligible"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.tier2.3",
            statement=(
                "Staging runs Tier 2 after shell smoke and before Tier 3/browser E2E, "
                "and the execution matrix names deployment_tier2_http_e2e separately "
                "(Was EPIC-008 AC8.18.3)."
            ),
            test=(
                "tests/tooling/test_tier2_http_e2e.py"
                "::test_AC8_18_3_staging_workflow_runs_tier2_http_before_tier3_browser_e2e"
            ),
            priority="P0",
            status="done",
        ),
        # ── group review-threads: PR review thread merge gate (was
        # EPIC-008 AC8.20), migration closeout, #1663 / #1718 ──
        ACRecord(
            id="AC-testing.review-threads.1",
            statement=(
                "The checker blocks (exit 1) when an unresolved P0/P1 (or unresolved "
                "Copilot) review thread exists (Was EPIC-008 AC8.20.1)."
            ),
            test=(
                "tests/tooling/test_check_pr_review_threads.py"
                "::test_AC8_20_1_unresolved_p0_blocks"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.review-threads.2",
            statement=(
                "Resolved/outdated threads and lower-severity (P2/P3/nit) unresolved "
                "threads do NOT block; they are reported (Was EPIC-008 AC8.20.2)."
            ),
            test=(
                "tests/tooling/test_check_pr_review_threads.py"
                "::test_AC8_20_2_resolved_p0_passes"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.review-threads.3",
            statement=(
                "The severity classification rule is documented in the CI/CD SSOT "
                "(Was EPIC-008 AC8.20.3)."
            ),
            test=(
                "tests/tooling/test_check_pr_review_threads.py"
                "::test_AC8_20_3_severity_rule_documented_in_ssot"
            ),
            priority="P1",
            status="done",
        ),
        # ── group seeded-journey: seeded no-LLM statement journey (was
        # EPIC-008 AC8.21), migration closeout, #1663 / #1718 ──
        ACRecord(
            id="AC-testing.seeded-journey.1",
            statement=(
                "A seeded no-LLM fixture materializes an already-parsed statement "
                "(PARSED envelope, linked ODS document, atomic transactions, "
                "non-empty original_filename, Decimal balances) with zero provider "
                "calls, bypassing the extraction/LLM seam (Was EPIC-008 AC8.21.1)."
            ),
            test=(
                "apps/backend/tests/e2e/test_seeded_statement_journey.py"
                "::test_seeded_fixture_bypasses_provider"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.seeded-journey.2",
            statement=(
                "The previously LLM-gated statement list -> detail journey runs in "
                "the no-LLM merge tier via the fixture: the list row and detail "
                "expose status=parsed, a non-empty original_filename (the "
                "stretched-link label, #1142), and the parsed transactions (Was "
                "EPIC-008 AC8.21.2)."
            ),
            test=(
                "apps/backend/tests/e2e/test_seeded_statement_journey.py"
                "::test_seeded_statement_list_and_detail_no_llm"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.seeded-journey.3",
            statement=(
                "The seeded statement's transactions endpoint resolves the parsed "
                "atomic transactions (descriptions, Decimal amounts, directions) with "
                "no provider call, so the downstream review/reconcile journey runs "
                "provider-free (Was EPIC-008 AC8.21.3)."
            ),
            test=(
                "apps/backend/tests/e2e/test_seeded_statement_journey.py"
                "::test_seeded_statement_transactions_endpoint_no_llm"
            ),
            priority="P0",
            status="done",
        ),
        # ── group matrix: test execution matrix as code (was EPIC-008
        # AC8.22), migration closeout, #1663 / #1718 ──
        ACRecord(
            id="AC-testing.matrix.1",
            statement=(
                "The checked-in docs/ssot/test-execution-matrix.yaml is exactly the "
                "view generated from common/testing/matrix.py (byte-identical via the "
                "--check-matrix CLI gate), and the generated YAML parses into the "
                "same path\u2192stage/ci_required rules the AC-traceability consumer reads "
                "\u2014 matrix-as-code cannot drift from the SSOT view (Was EPIC-008 "
                "AC8.22.1)."
            ),
            test=(
                "tests/tooling/test_execution_matrix_contract.py"
                "::test_AC8_22_1_generated_matrix_matches_checked_in_yaml"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.matrix.2",
            statement=(
                "preview.yml derives its in-runner E2E selection at runtime by "
                "eval'ing tools/test_selection.py --stage pr_preview_e2e --shell "
                "(tests, marker expression, parallelism all from the matrix) and "
                "carries no hardcoded tests/e2e/ path \u2014 the #1547 whitelist is "
                "structurally impossible to reintroduce (Was EPIC-008 AC8.22.2)."
            ),
            test=(
                "tests/tooling/test_execution_matrix_contract.py"
                "::test_AC8_22_2_preview_workflow_derives_selection_from_matrix"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.matrix.3",
            statement=(
                "The derived pre-merge selection contains exactly the audited, "
                "dependency-free rows (preserving the original in-runner set), every "
                "selected spec exists on disk, no llm-marked spec (verified against "
                "file content, not row metadata) can appear in the merge-blocking "
                "set, and the #1547 non-LLM vision hard gate is admitted after BOTH "
                "in-runner stack bugs it flushed out were root-caused and fixed in "
                "docker-compose.ci-e2e.yml \u2014 the double-/api NEXT_PUBLIC_API_URL 404 "
                "(PR #1587) and the #1589 FirstRunModal pointer interception (no "
                "provider wiring -> app-wide dismissible modal on every full "
                "navigation; fixed with placeholder wiring + unroutable AI_BASE_URL) "
                "\u2014 each admission a row flip, never a workflow edit (Was EPIC-008 "
                "AC8.22.3)."
            ),
            test=(
                "tests/tooling/test_execution_matrix_contract.py"
                "::test_AC8_22_3_preview_selection_is_audited_and_dependency_free"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.matrix.4",
            statement=(
                "Every root tests/e2e/test_*.py spec has a named ownership row in the "
                "matrix (needs + audit status + reason) and no stale row survives "
                "file removal \u2014 an unclassified E2E spec fails CI instead of silently "
                "landing outside any execution tier (Was EPIC-008 AC8.22.4)."
            ),
            test=(
                "tests/tooling/test_execution_matrix_contract.py"
                "::test_AC8_22_4_every_root_e2e_spec_has_a_named_row"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.matrix.5",
            statement=(
                "The --shell emission is valid, shlex-round-trippable bash (test "
                "array, quoted marker expression, parallelism) matching the in-code "
                "selection exactly, and an unknown stage is rejected with an explicit "
                "error (Was EPIC-008 AC8.22.5)."
            ),
            test=(
                "tests/tooling/test_execution_matrix_contract.py"
                "::test_AC8_22_5_shell_emission_round_trips"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.matrix.6",
            statement=(
                "The testing-package governance charter (execution matrix, package "
                "declaration protocol, E2E extension layer, fast interception, "
                "responsibility table) exists in common/testing/README.md, and "
                "docs/ssot/MANIFEST.yaml records common/testing/matrix.py as the "
                "test_execution_matrix owner with the generated YAML as a cross-ref "
                "(Was EPIC-008 AC8.22.6)."
            ),
            test=(
                "tests/tooling/test_execution_matrix_contract.py"
                "::test_AC8_22_6_charter_and_manifest_ownership"
            ),
            priority="P1",
            status="done",
        ),
        # ── group conformance: workflow selection conformance &
        # execution reconciliation (was EPIC-008 AC8.23), migration
        # closeout, #1663 / #1718 ──
        ACRecord(
            id="AC-testing.conformance.1",
            statement=(
                "Every junit-emitting pytest invocation in any workflow is registered "
                "in the matrix contracts and every registered contract has exactly "
                "one live invocation \u2014 fail-closed in both directions, so a selection "
                "change is impossible without touching the SSOT (Was EPIC-008 "
                "AC8.23.1)."
            ),
            test=(
                "tests/tooling/test_workflow_selection_conformance.py"
                "::test_AC8_23_1_every_workflow_pytest_invocation_is_registered"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.conformance.2",
            statement=(
                "Each registered invocation's -m expression and explicit path "
                "arguments equal the matrix constants (backend shards, integration, "
                "tier-1, staging core/provider/AI-OCR/version, production readonly) \u2014 "
                "marker semantics have exactly one owner (Was EPIC-008 AC8.23.2)."
            ),
            test=(
                "tests/tooling/test_workflow_selection_conformance.py"
                "::test_AC8_23_2_registered_invocations_match_matrix_selection"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.conformance.3",
            statement=(
                "The staging AI/OCR corpus (derived from @ac_proof metadata) and the "
                "matrix llm rows describe the same provider-dependent spec set, with "
                "the connectivity probe as the only declared difference \u2014 the two "
                "derivations cannot drift silently (Was EPIC-008 AC8.23.3)."
            ),
            test=(
                "tests/tooling/test_workflow_selection_conformance.py"
                "::test_AC8_23_3_staging_ai_ocr_corpus_aligns_with_matrix_llm_rows"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.conformance.4",
            statement=(
                "A behavioral pr_ci proof absent from aggregated PR junit evidence "
                "fails the reconciliation gate (wired after the score ratchet in "
                "ci.yml); present proofs pass, skipped-only is a hard fail (#1558: a "
                "pr_ci proof that only ever skips pre-merge is not executing its "
                "promise, though a skip in one shard with a real run in another "
                "passes), and parametrized/class-nested junit ids are matched "
                "correctly (Was EPIC-008 AC8.23.4)."
            ),
            test=(
                "tests/tooling/test_workflow_selection_conformance.py"
                "::test_AC8_23_4_pr_ci_evidence_reconciliation_gate"
            ),
            priority="P0",
            status="done",
        ),
        # ── group declarations: package test declarations, env
        # preconditions & mirror ratchet (was EPIC-008 AC8.24),
        # migration closeout, #1663 / #1718 ──
        ACRecord(
            id="AC-testing.declarations.1",
            statement=(
                "The seed packages (runtime, ledger, coverage) declare their owned "
                "test roots via TEST_ROOTS in their contract.py; the matrix "
                "aggregates them into the generated YAML's ownership: section (a "
                "dropped declaration fails the --check-matrix drift gate), every "
                "declared root exists on disk, and a root declared by two packages is "
                "rejected (Was EPIC-008 AC8.24.1)."
            ),
            test=(
                "tests/tooling/test_package_declaration_and_ratchet.py"
                "::test_AC8_24_1_seed_packages_declare_owned_test_roots"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.declarations.2",
            statement=(
                "Workflow pytest contracts declaring an environment precondition (the "
                "runtime-owned smoke gate, for the preview and staging core E2E "
                "stages) must run it before the pytest invocation in the same "
                "workflow \u2014 mechanized fault attribution: a red precondition aborts "
                "before tests start (Was EPIC-008 AC8.24.2)."
            ),
            test=(
                "tests/tooling/test_package_declaration_and_ratchet.py"
                "::test_AC8_24_2_e2e_stages_run_their_environment_precondition_first"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.declarations.3",
            statement=(
                "The mirror-assertion count over tests/tooling/ is locked behind a "
                "committed baseline that may only decrease: growth fails CI, --update "
                "refuses to raise the baseline, and paydown lowers it \u2014 with the "
                "eight marker-literal mirrors already redundant with AC8.23.2 deleted "
                "in the same change (Was EPIC-008 AC8.24.3)."
            ),
            test=(
                "tests/tooling/test_package_declaration_and_ratchet.py"
                "::test_AC8_24_3_mirror_assertion_ratchet_is_locked_and_only_goes_down"
            ),
            priority="P0",
            status="done",
        ),
        # ── group deploy-gates: deploy/staging/production workflow
        # gates (was EPIC-008 AC8.13 subset), migration closeout, #1663
        # / #1718 ──
        ACRecord(
            id="AC-testing.deploy-gates.1",
            statement=(
                "Production release runs prod-safe read-only E2E smoke (Was EPIC-008 "
                "AC8.13.9)."
            ),
            test=(
                "tests/e2e/test_production_readonly_smoke.py"
                "::test_AC8_13_9_production_public_runtime_contract"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.2",
            statement=(
                "Staging health check diagnoses API route 404 with route probes (Was "
                "EPIC-008 AC8.13.11)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_11_health_check_diagnoses_staging_api_route_404"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.3",
            statement=(
                "AI/OCR gate failures include statement validation context (Was "
                "EPIC-008 AC8.13.12)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_12_ai_ocr_gate_failure_includes_statement_context"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.4",
            statement=(
                "Staging deploy uses workflow-level singleton concurrency plus an "
                "in-job FIFO guard to prevent duplicate concurrent staging mutation "
                "and bounds E2E gate duration with phase timing logs (Was EPIC-008 "
                "AC8.13.13)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_13_staging_deploy_fast_fail_guardrails"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.5",
            statement=(
                "Provider-backed staging AI/OCR gate runs separately from deploy "
                "health (Was EPIC-008 AC8.13.14)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_14_staging_ai_ocr_gate_is_separate_deploy_job"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.6",
            statement=(
                "Provider-backed staging AI/OCR gate runs inside a manual staging "
                "dispatch (inheriting workflow_dispatch) and via the on-demand "
                "deploy.yml, never auto-after-CI (Was EPIC-008 AC8.13.21)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_21_staging_ai_ocr_gate_runs_under_manual_dispatch"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.7",
            statement=(
                "Staging deploys an explicitly supplied published release version_ref "
                "(vX.Y.Z tag) on workflow_dispatch; it does not build or promote "
                "images inside the deploy workflow (Was EPIC-008 AC8.13.22)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_22_staging_deploys_manually_dispatched_version_ref"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.8",
            statement=(
                "Automatic staging deploy health and AI/OCR validation run in one "
                "serialized post-merge workflow unit (Was EPIC-008 AC8.13.23)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_23_post_merge_deploy_and_ai_ocr_are_one_serial_unit"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.9",
            statement=(
                "Main CI builds SHA-tagged images, deploy.yml promotes those digests "
                "to an immutable vX.Y.Z release tag, and staging deploy consumes that "
                "tag without rebuilding or moving a staging tag (Was EPIC-008 "
                "AC8.13.36)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_36_post_merge_reuses_sha_tagged_staging_images"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.10",
            statement=(
                "PR CI dry-runs staging image builds before merge; main push CI is "
                "the only path that pushes SHA-tagged images (Was EPIC-008 "
                "AC8.13.40)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_40_pr_ci_dry_runs_staging_image_builds_before_merge"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.11",
            statement=(
                "Staging AI/OCR gates publish audit input inventory and replay "
                "summary fields (Was EPIC-008 AC8.13.49)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_49_staging_ai_ocr_gate_publishes_audit_inventory_and_summary"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.12",
            statement=(
                "Staging deploy is manual (workflow_dispatch) only with a required "
                "deploy_v2-aligned version_ref input; it does not auto-follow main CI "
                "and does not poll for CI in-job (Was EPIC-008 AC8.13.51)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_51_staging_deploy_is_manual_dispatch_only"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.13",
            statement=(
                "Production release dry-run validates release prerequisites and image "
                "builds through shared release evidence/image digest tools without "
                "production mutation (Was EPIC-008 AC8.13.52)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_52_production_release_dry_run_does_not_mutate_production"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.14",
            statement=(
                "Post-merge staging deploys only for runtime, deploy, E2E, staging "
                "workflow, toolchain, or infra-submodule changes (Was EPIC-008 "
                "AC8.13.55)."
            ),
            test=(
                "tests/tooling/test_ci_change_classifier.py"
                "::test_AC8_13_55_staging_only_runs_for_runtime_deploy_or_e2e_changes"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.15",
            statement=(
                "Deploy workflows do not keep no-op dependency checks or warning-only "
                "performance probes that cannot block release risk (Was EPIC-008 "
                "AC8.13.60)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_60_deploy_workflows_have_no_nonblocking_noop_gates"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.16",
            statement=(
                "Production release verifies DB, S3, app vendor-neutral OTEL "
                "readiness, API, and frontend before completing deploy (proving the "
                "observability backend ingests is infra2's job) (Was EPIC-008 "
                "AC8.13.64)."
            ),
            test=(
                "tests/tooling/test_production_infra_smoke.py"
                "::test_AC8_13_64_production_infra_smoke_cli_reports_failure"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.17",
            statement=(
                "Production release reuses successful main CI proof instead of "
                "rerunning container-backed tests in the release lane (Was EPIC-008 "
                "AC8.13.65)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_52_production_release_dry_run_does_not_mutate_production"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.18",
            statement=(
                "Production release preserves deployed version metadata from image "
                "build through Dokploy runtime health (Was EPIC-008 AC8.13.67)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_67_production_release_preserves_version_metadata"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.19",
            statement=(
                "Staging is mutated only by an explicit manual workflow_dispatch with "
                "a required release version_ref input; no auto path can promote "
                "images or change Dokploy, and structured deploy failure context is "
                "preserved (Was EPIC-008 AC8.13.93)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_93_staging_promotion_requires_manual_dispatch"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.20",
            statement=(
                "Main post-merge staging publishes one commit-level Post-merge "
                "Delivery check that fails release-critical staging build/deploy and "
                "provider connectivity failures, while recording right-shifted full "
                "AI/OCR regression evidence without blocking production eligibility "
                "(Was EPIC-008 AC8.13.103)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_103_post_merge_delivery_summary_check_aggregates_staging_gates"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.21",
            statement=(
                "Post-merge staging keeps FIFO ordering but collapses train wait, "
                "staging classification, and deploy into one runner job to avoid a "
                "second GitHub Actions scheduling gap before staging mutation (Was "
                "EPIC-008 AC8.13.105)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_13_staging_deploy_fast_fail_guardrails"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.22",
            statement=(
                "Main post-merge staging deploy failures publish structured failure "
                "domain, failed step, and failure summary in the deploy context "
                "artifact and Post-merge Delivery summary so deploy_v2 dependency "
                "setup, Dokploy rollout, route health, E2E setup, and application E2E "
                "failures can be separated without manual log scraping (Was EPIC-008 "
                "AC8.13.108)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_93_staging_promotion_requires_manual_dispatch"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.23",
            statement=(
                "Post-merge staging AI/OCR gate tests use isolated users, "
                "browser-cookie auth, deterministic UI waits, and cleanup-capable "
                "test accounts; PR tooling rejects shared mutable users, localStorage "
                "bearer tokens, and generic deployed-env idle waits before "
                "provider-backed replay (Was EPIC-008 AC8.13.109)."
            ),
            test=(
                "tests/tooling/test_staging_ai_ocr_gate_contract.py"
                "::test_AC8_13_109_ai_ocr_gate_tests_use_isolated_users"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.24",
            statement=(
                "Sparse Env x Stage reviews record the three newest successful and "
                "three newest failed evidence samples for active delivery lanes, then "
                "summarize delivery-speed balance, end-to-end consistency, quality "
                "fallback, resource leak candidates, and the safe simplification "
                "boundary (Was EPIC-008 AC8.13.113)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_113_sparse_matrix_evidence_and_resource_leak_audit_are_recorded"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.25",
            statement=(
                "Post-merge \u2192 staging start latency is reduced by removing redundant "
                "heavy re-run on push to main (Was EPIC-008 AC8.13.116)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_116_skip_heavy_ci_on_main_push"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.26",
            statement=(
                "One delivery hardening PR contracts the known leak paths: PR preview "
                "leftovers, legacy GHCR PR tag accumulation, stale staging or "
                "production routes, provider-backed external-state residue, and "
                "Docker build cache and stopped containers, while preserving the "
                "sparse Env x Stage speed boundary (Was EPIC-008 AC8.13.119)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_119_delivery_resource_leak_hardening_is_contracted"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.27",
            statement=(
                "Provider-risk staging changes run one dedicated real AI provider "
                "connectivity smoke after deployed health and non-LLM E2E; transient "
                "provider 5xx/timeouts degrade delivery without failing main, while "
                "provider 4xx stays a hard gate (Was EPIC-008 AC8.13.120)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_120_staging_runs_lightweight_provider_connectivity_smoke"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.28",
            statement=(
                "The staging AI/OCR gate summarizes its JUnit output into real "
                "pass/fail counts and names the failing corpus docs (instead of a "
                "binary \"Failures observed: 1+\" with verified counts \"unknown\"), so a "
                "red gate is diagnosable "
                "([#1089](https://github.com/wangzitian0/finance_report/issues/1089)) "
                "(Was EPIC-008 AC8.13.137)."
            ),
            test=(
                "tests/tooling/test_staging_ai_ocr_gate_contract.py"
                "::test_AC8_13_137_summarize_junit_reports_per_doc_failures"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.29",
            statement=(
                "Production release rolls back through deploy_v2 to the pre-deploy "
                "production version and confirms health when a post-deploy route, "
                "infrastructure, smoke, or read-only E2E gate fails after mutation "
                "(Was EPIC-008 AC8.13.144)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_144_production_release_rolls_back_with_deploy_v2_after_post_deploy_failure"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.30",
            statement=(
                "The report-branch-main auto preview dispatch runs only after "
                "successful main CI publishes SHA images, skips stale workflow_run "
                "completions, and infra2 deploy_v2 refuses to deploy branch-form main "
                "unless it resolves to the exact payload SHA (Was EPIC-008 "
                "AC8.13.146)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_146_report_main_dispatch_waits_for_ci_images"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.31",
            statement=(
                "The staging AI/OCR production-promotion blocking path runs only the "
                "minimal AI/OCR Canary corpus \u2014 one representative brokerage "
                "upload\u2192parse\u2192import\u2192value liveness check "
                "(tests/e2e/test_brokerage_upload_to_portfolio_value.py) with no "
                "broad audit assertions (report_verifications == 0); the canary "
                "corpus is curated in tools/staging_ai_ocr_gate_contract.py "
                "(canary_files()) as a subset of the derived llm post-merge proofs "
                "and runs via the reusable gate's corpus: canary input (Was EPIC-008 "
                "AC8.13.156)."
            ),
            test=(
                "tests/tooling/test_staging_ai_ocr_gate_contract.py"
                "::test_AC8_13_156_canary_corpus_is_minimal_liveness"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.32",
            statement=(
                "The heavy LLM audit journeys (full statement journey, four-asset "
                "net-worth golden path, personal financial report package) run as a "
                "separate audit-replay.yml job on schedule: (nightly) + "
                "workflow_dispatch: that calls the reusable gate with corpus: "
                "audit_replay and blocking: false, so the comprehensive corpus does "
                "NOT block production promotion by default (Was EPIC-008 AC8.13.157)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_157_audit_replay_workflow_is_nightly_and_nonblocking"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.33",
            statement=(
                "The canary's provider transient-failure classification is owned by "
                "the Staging Provider Gate: the inline ai-ocr-gate canary only starts "
                "after provider-gate passes, where a 4xx/config error blocks delivery "
                "(config-failure) while a 5xx/timeout is a non-blocking degraded "
                "status (Was EPIC-008 AC8.13.158)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_158_canary_transient_classification_owned_by_provider_gate"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.34",
            statement=(
                "Anti-regression: the blocking-path canary corpus and the "
                "audit-replay corpus are disjoint, every heavy audit journey is in "
                "the audit-replay corpus (never the canary), and the deploy-path "
                "ai-ocr-gate resolves corpus: canary so the heavy journeys cannot "
                "creep back into the blocking path (Was EPIC-008 AC8.13.159)."
            ),
            test=(
                "tests/tooling/test_staging_ai_ocr_gate_contract.py"
                "::test_AC8_13_159_blocking_path_excludes_heavy_audit_journeys"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-testing.deploy-gates.35",
            statement=(
                "SSOT docs/ssot/ci-cd.md clearly distinguishes the blocking, minimal "
                "AI/OCR Canary from the nightly/manual, comprehensive Audit Replay, "
                "and records the canary-vs-audit split as a deliberate keep_separate "
                "decision in the gate inventory (Was EPIC-008 AC8.13.160)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_160_ci_cd_distinguishes_canary_from_audit_replay"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        # ── group product-gates: product-journey hard gates & fixture
        # contracts (was EPIC-008 AC8.13 subset), migration closeout,
        # #1663 / #1718 ──
        ACRecord(
            id="AC-testing.product-gates.1",
            statement=(
                "Critical staging E2E skips fail the deploy gate (Was EPIC-008 "
                "AC8.13.6)."
            ),
            test=(
                "tests/tooling/test_critical_skip_gate.py"
                "::test_AC8_13_6_strict_gates_off_never_converts"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.product-gates.2",
            statement=(
                "Deterministic upload-to-dashboard gate runs as a critical fresh-user "
                "staging E2E (Was EPIC-008 AC8.13.28)."
            ),
            test=(
                "tests/e2e/test_vision_upload_to_dashboard_hard_gate.py"
                "::test_statement_upload_to_dashboard_vision_hard_gate"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.product-gates.3",
            statement=(
                "Stage 1 review auto-posts journal entries from the deterministic "
                "fixture (Was EPIC-008 AC8.13.29)."
            ),
            test=(
                "tests/e2e/test_vision_upload_to_dashboard_hard_gate.py"
                "::test_statement_upload_to_dashboard_vision_hard_gate"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.product-gates.4",
            statement=(
                "Reconciliation rerun is idempotent and Stage 2 run review reaches a "
                "cleared completion state (Was EPIC-008 AC8.13.30)."
            ),
            test=(
                "tests/e2e/test_vision_upload_to_dashboard_hard_gate.py"
                "::test_statement_upload_to_dashboard_vision_hard_gate"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.product-gates.5",
            statement=(
                "Processing Account summary and pending page stay visible and correct "
                "for the cleared run (Was EPIC-008 AC8.13.31)."
            ),
            test=(
                "tests/e2e/test_vision_upload_to_dashboard_hard_gate.py"
                "::test_statement_upload_to_dashboard_vision_hard_gate"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.product-gates.6",
            statement=(
                "Dashboard, balance sheet, income statement, and cash-flow totals "
                "exactly match the deterministic upload fixture (Was EPIC-008 "
                "AC8.13.32)."
            ),
            test=(
                "tests/e2e/test_vision_upload_to_dashboard_hard_gate.py"
                "::test_statement_upload_to_dashboard_vision_hard_gate"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.product-gates.7",
            statement=(
                "Four-asset as-of net worth golden path runs as a critical fresh-user "
                "post-merge E2E (Was EPIC-008 AC8.13.42)."
            ),
            test=(
                "tests/e2e/test_four_asset_net_worth_golden_path.py"
                "::test_four_asset_as_of_net_worth_golden_path"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.product-gates.8",
            statement=(
                "Personal report package representative fixture contract defines bank "
                "cash, income/expense activity, brokerage holdings, manual property "
                "valuation, liability, restricted compensation, notes, traceability "
                "anchors, and exact Decimal expected outputs (Was EPIC-008 "
                "AC8.13.83)."
            ),
            test=(
                "tests/tooling/test_personal_report_package_fixture_contract.py"
                "::test_AC8_13_83_representative_package_fixture_contract_defines_exact_outputs"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.product-gates.9",
            statement=(
                "Personal report package post-merge E2E consumes the representative "
                "fixture contract instead of duplicating financial constants or "
                "expected totals inline (Was EPIC-008 AC8.13.84)."
            ),
            test=(
                "tests/tooling/test_personal_report_package_fixture_contract.py"
                "::test_AC8_13_84_personal_package_e2e_consumes_representative_fixture_contract"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.product-gates.10",
            statement=(
                "Personal financial report package macro proof is promoted to covered "
                "only when the representative fixture contract ACs are part of the "
                "critical proof matrix (Was EPIC-008 AC8.13.85)."
            ),
            test=(
                "tests/tooling/test_personal_report_package_fixture_contract.py"
                "::test_AC8_13_85_personal_package_macro_proof_is_promoted_after_fixture_contract"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.product-gates.11",
            statement=(
                "Personal report package fixture contract pins brokerage, dividend, "
                "and market-price expected outputs as Decimal-safe audit fixtures "
                "(Was EPIC-008 AC8.13.87)."
            ),
            test=(
                "tests/tooling/test_personal_report_package_fixture_contract.py"
                "::test_AC8_13_87_personal_package_fixture_pins_brokerage_dividend_and_market_price_outputs"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.product-gates.12",
            statement=(
                "Personal report package post-merge E2E consumes the audit-grade "
                "brokerage, dividend, market-price, and traceability identifier "
                "expected outputs (Was EPIC-008 AC8.13.88)."
            ),
            test=(
                "tests/tooling/test_personal_report_package_fixture_contract.py"
                "::test_AC8_13_88_personal_package_e2e_consumes_audit_grade_expected_outputs"
            ),
            priority="P0",
            status="done",
        ),
    ],
)

# Test roots folded in from the `coverage` package (now common/testing/coverage/).
TEST_ROOTS: tuple[str, ...] = (
    "tests/tooling/test_coverage_policy.py",
    "tests/tooling/test_coverage_analyzer.py",
    "tests/tooling/test_calculate_unified_coverage.py",
    "tests/tooling/test_coverage_artifact_preflight.py",
)
