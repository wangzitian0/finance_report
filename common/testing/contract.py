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
                "apps/backend/tests/e2e/test_core_journeys.py::test_journal_entry_crud"
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
        ACRecord(
            id="AC-testing.review-threads.4",
            statement=(
                "A Copilot thread classifies as blocking using the real "
                "author.login the GraphQL reviewThreads API actually returns "
                '("copilot-pull-request-reviewer", no "[bot]" suffix) -- '
                'not only a synthetic "[bot]"-suffixed fixture value '
                "(2026-07-12 regression: this mismatch let every real "
                "Copilot thread silently classify as non-blocking)."
            ),
            test=(
                "tests/tooling/test_check_pr_review_threads.py"
                "::test_copilot_thread_real_login_without_bot_suffix_is_blocking"
            ),
            priority="P0",
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
                'binary "Failures observed: 1+" with verified counts "unknown"), so a '
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
        ACRecord(
            id="AC-testing.deploy-gates.36",
            statement=(
                "Every main-branch commit's :<sha> image is independently "
                "verified to actually exist in the registry, not just "
                "'the build step reported success': verify-sha-image-published "
                "runs after container-images on main push and re-inspects the "
                "registry via the same digest primitive release.yml's dry-run "
                "uses for release tags, so a silent publish failure is caught "
                "at commit time instead of later at promote (#1759, W4 of #1435)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC_testing_deploy_gates_36_every_main_commit_image_is_independently_verified"
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
        # ── group preview: PR-preview lifecycle & Dokploy semantics
        # (was EPIC-008 AC8.13 subset), migration closeout, #1663 /
        # #1718 ──
        ACRecord(
            id="AC-testing.preview.1",
            statement=(
                "The app performs no Dokploy preview reclaim \u2014 on PR close it "
                "dispatches a vendor-neutral teardown to infra2 (which owns the 1:1 "
                "reclaim); the app keeps no cleanup/reconcile entrypoints, no "
                "host-hygiene commands, and emits no raw Dokploy responses (Was "
                "EPIC-008 AC8.13.38)."
            ),
            test=(
                "tests/tooling/test_cleanup_pr_preview_resources.py"
                "::test_AC8_13_38_legacy_cleanup_entrypoints_are_removed"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.preview.2",
            statement=(
                "PR preview non-LLM E2E uses strict gates and parallelism while "
                "narrowing execution to runtime/API/UI preview-relevant paths instead "
                "of the staging regression set (Was EPIC-008 AC8.13.46)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_46_pr_preview_non_llm_gate_matches_staging_strict_parallelism"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.preview.3",
            statement=(
                "One lifecycle tool stands PR previews UP (deploy) and writes stable "
                "preview metadata; on PR close the workflow dispatches a "
                "preview-teardown signal to infra2 \u2014 the app owns no Dokploy reclaim "
                "(cleanup/reconcile/delete) (Was EPIC-008 AC8.13.71)."
            ),
            test=(
                "tests/tooling/test_pr_preview_lifecycle.py"
                "::test_AC8_13_71_close_dispatches_preview_teardown_to_infra2"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.preview.4",
            statement=(
                "Dokploy deploy diagnostics redact raw responses, log only "
                "allowlisted effective environment/config details, parse deployment "
                "records as typed object records, fail before readiness when fixed "
                "deploy_v2 sees rollout error/no terminal new record, and retain "
                "redacted rollout diagnostics for legacy preview compatibility (Was "
                "EPIC-008 AC8.13.72)."
            ),
            test=(
                "tests/tooling/test_dokploy_redaction.py"
                "::test_AC8_13_72_common_dokploy_call_redacts_non_200_body"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.preview.5",
            statement=(
                "The app owns no VPS host hygiene \u2014 generic host GC "
                "(Docker/journald/disk prune) is infra2-owned "
                "(tools/host_hygiene_schedule.py + the ops-checks re-ensure job); the "
                "app ships no vps_host_hygiene module and provisions no Dokploy "
                "host-schedule (Was EPIC-008 AC8.13.73)."
            ),
            test=(
                "tests/tooling/test_cleanup_pr_preview_resources.py"
                "::test_AC8_13_73_app_owns_no_vps_host_hygiene"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.preview.6",
            statement=(
                "The app's scheduled maintenance performs no Dokploy preview "
                "reconcile and no host hygiene \u2014 it only prunes the app's own stale "
                "GHCR PR image tags (Dokploy preview reclaim is infra2-owned) (Was "
                "EPIC-008 AC8.13.74)."
            ),
            test=(
                "tests/tooling/test_cleanup_pr_preview_resources.py"
                "::test_AC8_13_74_maintenance_cleanup_is_ghcr_pruning_only"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.preview.7",
            statement=(
                "The runner-local full-stack smoke/E2E gate runs synchronously on "
                "pull_request (the merge authority, a real required check, not async "
                "via workflow_run); the on-demand persistent Dokploy preview is built "
                "from the PR source on the host without pushing, preflighting, "
                "pulling, or deleting PR preview images (Was EPIC-008 AC8.13.89)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_89_pr_preview_follows_ci_without_pr_image_builds"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.preview.8",
            statement=(
                "Legacy Dokploy preview composes preserve compose identity, update "
                "allowlisted deploy env, and re-run Dokploy compose.redeploy without "
                "a pre-stop or separate compose.start call so historical "
                "cleanup/reconciliation compatibility can still reason about stuck "
                "previews safely (Was EPIC-008 AC8.13.98)."
            ),
            test=(
                "tests/tooling/test_pr_preview_lifecycle.py"
                "::test_AC8_13_98_existing_preview_compose_is_redeployed_without_pre_stop"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.preview.9",
            statement=(
                "Runner preview readiness is bounded and observable before smoke/E2E; "
                "legacy Dokploy route diagnostics remain as compatibility evidence "
                "for historical preview cleanup/reconciliation tooling (Was EPIC-008 "
                "AC8.13.100)."
            ),
            test=(
                "tests/tooling/test_pr_preview_lifecycle.py"
                "::test_AC8_13_100_pr_preview_runner_readiness_is_bounded_and_observable"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.preview.10",
            statement=(
                "PR preview E2E consumes the runner-local http://localhost:8080 URL "
                "as the merge-authority gate; after it passes, a non-blocking "
                "persistent Dokploy preview is deployed at report-pr-<N>.<domain> and "
                "released via compose.delete on PR close; lifecycle helpers preserve "
                "stable/commit preview URL derivation (Was EPIC-008 AC8.13.101)."
            ),
            test=(
                "tests/tooling/test_pr_preview_lifecycle.py"
                "::test_AC8_13_101_preview_app_url_prefers_stable_alias"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.preview.11",
            statement=(
                "The PR-preview deploy helpers keep bounded rollout diagnostics, "
                "redaction, transient retry handling, and stuck-compose recovery "
                "semantics so a preview deploy fails safe even though current default "
                "PR preview no longer creates PR images (Was EPIC-008 AC8.13.102)."
            ),
            test=(
                "tests/tooling/test_pr_preview_lifecycle.py"
                "::test_AC8_13_102_preview_network_is_pr_scoped_to_limit_subnet_usage"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.preview.12",
            statement=(
                "PR preview uploads runner preview context artifacts without PR image "
                "preflight, while legacy lifecycle deploy helpers still redact "
                "context for compatibility tests (Was EPIC-008 AC8.13.107)."
            ),
            test=(
                "tests/tooling/test_pr_preview_lifecycle.py"
                "::test_AC8_13_107_deploy_action_fails_fast_on_missing_required_inputs"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.preview.13",
            statement=(
                "The in-runner E2E gate runs synchronously on pull_request as a real "
                "required check a fast/auto merge cannot bypass (not async via "
                "workflow_run, which a merge could outrun); PR close triggers "
                "cleanup, not a gate (Was EPIC-008 AC8.13.114)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_114_pr_preview_follows_successful_ci_workflow_run"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.preview.14",
            statement=(
                "Runner preview readiness is bounded before smoke/E2E starts, with "
                "stack logs emitted on failure (Was EPIC-008 AC8.13.115)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_115_readiness_fail_fast"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.preview.15",
            statement=(
                "PR preview waits stay bounded: current runner preview has a hard "
                "workflow timeout and legacy Dokploy busy-queue extensions cannot "
                "exceed the compatibility rollout deadline (Was EPIC-008 AC8.13.125)."
            ),
            test=(
                "tests/tooling/test_pr_preview_lifecycle.py"
                "::test_AC8_13_125_busy_dokploy_queue_cannot_extend_past_rollout_deadline"
            ),
            priority="P1",
            status="done",
        ),
        # ── group classifier: CI change classification (was EPIC-008
        # AC8.13 subset), migration closeout, #1663 / #1718 ──
        ACRecord(
            id="AC-testing.classifier.1",
            statement=(
                "CI change classification skips backend/frontend/coverage for "
                "lightweight changes and uses deterministic npm cache (Was EPIC-008 "
                "AC8.13.16)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_16_ci_change_classification_and_frontend_cache"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.classifier.2",
            statement=(
                "CI change classification is covered by multi-commit and markdown "
                "edge-case regression tests (Was EPIC-008 AC8.13.20)."
            ),
            test=(
                "tests/tooling/test_ci_change_classifier.py"
                "::test_AC8_13_20_ci_workflow_changes_are_heavy_except_docs_workflow"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.classifier.3",
            statement=(
                "PR preview relevance classification includes preview workflow, "
                "lifecycle, and config changes while excluding docs-only and app "
                "test-only changes (Was EPIC-008 AC8.13.96)."
            ),
            test=(
                "tests/tooling/test_ci_change_classifier.py"
                "::test_AC8_13_96_pr_preview_classifier_includes_preview_infrastructure_paths"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.classifier.4",
            statement=(
                "CI change classification exposes table-driven env/stage rules so "
                "shared runtime paths cannot drift between PR preview and staging "
                "deployed proof (Was EPIC-008 AC8.13.97)."
            ),
            test=(
                "tests/tooling/test_ci_change_classifier.py"
                "::test_AC8_13_97_deployed_env_classifiers_share_common_runtime_rules"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.classifier.5",
            statement=(
                "Automatic staging AI/OCR runs only for provider, extraction, "
                "statement parsing, PDF fixture, AI/OCR workflow, or critical LLM "
                "proof path changes; normal runtime deploys keep staging smoke/E2E "
                "but skip provider spend (Was EPIC-008 AC8.13.104)."
            ),
            test=(
                "tests/tooling/test_ci_change_classifier.py"
                "::test_AC8_13_104_staging_ai_ocr_runs_only_for_provider_risk_paths"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.classifier.6",
            statement=(
                "CI change classification emits structured Env x Stage JSON outputs "
                "and matrix summaries as the sole machine-readable gate contract; the "
                "per-env legacy scalar outputs (pr_preview_required, "
                "staging_required, staging_ai_ocr_required) are retired now that "
                "every workflow consumer derives its own scalar from the structured "
                "matrix (Was EPIC-008 AC8.13.110)."
            ),
            test=(
                "tests/tooling/test_ci_change_classifier.py"
                "::test_AC8_13_110_github_outputs_include_structured_env_stage_matrix"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.classifier.7",
            statement=(
                "CI change classification structured Env x Stage outputs cover the "
                "complete environment axis (local, pr, pr-preview, staging, prd) "
                "while keeping PR heavy gating and deployed-environment gates "
                "represented as matrix cells (Was EPIC-008 AC8.13.111)."
            ),
            test=(
                "tests/tooling/test_ci_change_classifier.py"
                "::test_AC8_13_111_static_stage_rejects_non_static_environments"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.classifier.8",
            statement=(
                "Delivery-engine recommendations, SSOT, workflow gates, and contract "
                "tests stay aligned around structured Env x Stage consumers as the "
                "sole gate contract; the per-env legacy scalar classifier outputs are "
                "retired and the simplification path is recorded as complete (Was "
                "EPIC-008 AC8.13.112)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_112_sparse_matrix_recommendation_tracks_simplification_path"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.classifier.9",
            statement=(
                "Workflow consumers keep Env x Stage as the classifier-owned source "
                "of truth: CI and PR preview jobs normalize structured classifier "
                "outputs into compatibility scalar outputs, downstream jobs consume "
                "only those normalized outputs, and no downstream job reimplements "
                "changed-path classification or ad hoc path logic (Was EPIC-008 "
                "AC8.13.152)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_152_workflow_consumers_keep_classification_single_owned"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-testing.classifier.10",
            statement=(
                "The change classifier computes a per-component "
                "(backend/frontend/tools/common) change signal alongside the existing "
                'Env\u00d7Stage matrix \u2014 fail-closed to "all changed" on an undetected '
                "diff \u2014 and exposes it as plain {component}_changed GITHUB_OUTPUT "
                "scalars plus a ready-to-use coverage_gate_components comma list, so "
                "downstream jobs never reimplement path classification (extends "
                "AC8.13.152's single-owned-classification principle to component "
                "scope, #1689) (Was EPIC-008 AC8.13.161)."
            ),
            test=(
                "tests/tooling/test_ci_change_classifier.py"
                "::test_AC8_13_161_component_changed_isolates_a_single_component"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        # ── group ci-structure: CI job structure & fan-in (was EPIC-008
        # AC8.13 subset), migration closeout, #1663 / #1718 ──
        ACRecord(
            id="AC-testing.ci-structure.1",
            statement=(
                "Full CI starts deterministic test and image jobs after change "
                "classification while finish aggregates lint, AC traceability, tests, "
                "image validation, coverage, and skipped-job semantics (Was EPIC-008 "
                "AC8.13.25)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_25_full_ci_aggregates_static_traceability_and_test_gates"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.ci-structure.2",
            statement=(
                "CI metrics contract fails when source roots, coverage policy, "
                "workflow gates, or AC traceability semantics drift (Was EPIC-008 "
                "AC8.13.26)."
            ),
            test=(
                "tests/tooling/test_ci_metrics_contract.py"
                "::test_AC8_13_26_ci_workflow_runs_metrics_contract_and_defines_metric_semantics"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.ci-structure.3",
            statement=(
                "Shared E2E setup caches Python virtualenv and Playwright browser "
                "artifacts for staging and preview gates and exports repository-root "
                "PYTHONPATH for stable tests.e2e.* imports (Was EPIC-008 AC8.13.33)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_33_e2e_setup_caches_virtualenv_and_playwright_browsers"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.ci-structure.4",
            statement=(
                "CI and post-merge workflows append queue, execution, and per-job "
                "timing summaries to GitHub Step Summary (Was EPIC-008 AC8.13.34)."
            ),
            test=(
                "tests/tooling/test_github_workflow_timing_summary.py"
                "::test_AC8_13_34_format_duration_uses_compact_minutes"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.ci-structure.5",
            statement=(
                "CI fast feedback jobs start after change classification without "
                "waiting for behavior-only backend gates (Was EPIC-008 AC8.13.86)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_86_fast_feedback_jobs_do_not_wait_for_behavior_gates"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.ci-structure.6",
            statement=(
                "Backend Tier-1 API E2E keeps PR fail-fast for speed but push/main "
                "runs the full Tier-1 suite so the JUnit artifact reports every "
                "failing API journey in one run (Was EPIC-008 AC8.13.145)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_145_backend_tier1_pr_fail_fast_but_main_reports_all_failures"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.ci-structure.7",
            statement=(
                "Frontend PR CI is split into build/typecheck, Vitest coverage, "
                "provider-free Playwright, and telemetry E2E jobs while preserving "
                "coverage-frontend, frontend Vitest JUnit evidence, unified-coverage "
                "fan-in, AC behavioral ratchet fan-in, and finish aggregation over "
                "every frontend gate (Was EPIC-008 AC8.13.147)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_147_frontend_ci_split_preserves_merge_authority"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.ci-structure.8",
            statement=(
                "Backend fast-test CI shards rebalance the current critical path with "
                "a 5-way pytest-split matrix, a committed duration seed, "
                "least-duration assignment, and a seed-size guard so CI cannot "
                "silently fall back to unseeded even splitting (Was EPIC-008 "
                "AC8.13.148)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_148_backend_shards_use_seeded_5_way_split"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.ci-structure.9",
            statement=(
                "CI fan-in jobs trim post-backend tail work without weakening merge "
                "authority: unified coverage runs stdlib Python over scoped coverage "
                "artifacts, and the AC behavioral ratchet downloads only "
                "JUnit-producing test-context artifacts (Was EPIC-008 AC8.13.149)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_149_fan_in_jobs_download_only_required_artifacts"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.ci-structure.10",
            statement=(
                "frontend-telemetry-e2e is right-moved off PRs that touch no "
                "apps/frontend/ path (mirrors container-images' image_build_required "
                "pattern): it always runs on a main/release push or manual dispatch, "
                "and a skip is a pass (not a gap) in finish's aggregation, so "
                "unrelated PRs stop paying its browser-install wall-clock cost "
                "(#1689) (Was EPIC-008 AC8.13.162)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_162_frontend_telemetry_e2e_is_right_moved_and_skip_is_a_pass"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        # ── group coverage: coverage/LCOV gates (was EPIC-008 AC8.13
        # subset), migration closeout, #1663 / #1718 ──
        ACRecord(
            id="AC-testing.coverage.1",
            statement=(
                "Unified coverage policy keeps CI source tree, LCOV reports, and "
                "Coveralls uploads aligned (Was EPIC-008 AC8.13.15)."
            ),
            test=(
                "tests/tooling/test_ci_metrics_contract.py"
                "::test_AC8_13_26_future_app_source_roots_must_be_in_coverage_policy"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.coverage.2",
            statement=(
                "Pull requests do not publish Coveralls status contexts; main-only "
                "Coveralls reporting remains separate from local deterministic "
                "coverage gates (Was EPIC-008 AC8.13.27)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_27_coveralls_uploads_are_reporting_only"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.coverage.3",
            statement=(
                "Coveralls uploads strip branch counters so external percentages "
                "track the line-only unified coverage gate (Was EPIC-008 AC8.13.66)."
            ),
            test=(
                "tests/tooling/test_strip_lcov_branches.py"
                "::test_AC8_13_66_strip_lcov_branches_cli_exits_zero"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.coverage.4",
            statement=(
                "Reporting-only coverage gate summary cannot fail the final CI "
                "aggregation job if GitHub Step Summary writes fail (Was EPIC-008 "
                "AC8.13.75)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_75_coverage_gate_summary_is_nonblocking"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.coverage.5",
            statement=(
                "Main CI automatically opens or updates a reviewed baseline PR when "
                "unified-coverage.json rises, while PR CI keeps the committed "
                "no-regression gate and no new required status context is introduced "
                "(Was EPIC-008 AC8.13.143)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_143_unified_coverage_updates_baseline_through_pr_not_direct_main_push"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.coverage.6",
            statement=(
                "calculate_unified_coverage's no-regression gate accepts a "
                "--gate-components/COVERAGE_GATE_COMPONENTS scope: on pull_request "
                "events it BLOCKS only on regressions in the components the PR "
                "actually changed (an unrelated component's regression, and the "
                'blended "unified" total, are still computed and reported but do not '
                "fail the job); every component is still merged into "
                "unified-coverage.json regardless of scope, and a push to main always "
                "omits the scope (full, unscoped, unchanged-strict gate) (#1689) (Was "
                "EPIC-008 AC8.13.163)."
            ),
            test=(
                "tests/tooling/test_coverage_artifact_preflight.py"
                "::test_AC8_13_163_scoped_to_the_regressed_component_still_fails"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        # ── group acgates: AC-index / critical-proof / traceability
        # gates (was EPIC-008 AC8.13 subset), migration closeout, #1663
        # / #1718 ──
        ACRecord(
            id="AC-testing.acgates.1",
            statement=(
                "AC registry generation writes small generated indexes, materializes "
                "entries from EPIC docs plus explicit overrides, and preserves no "
                "duplicate feature/infra ownership (Was EPIC-008 AC8.13.17)."
            ),
            test=(
                "tests/tooling/test_generate_ac_registry.py"
                "::test_main_appends_missing_ac_without_rewriting_current_epic_text"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.2",
            statement=(
                "AC traceability audit is uploaded as a CI artifact instead of "
                "failing on a stale committed report (Was EPIC-008 AC8.13.24)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_24_ac_traceability_uploads_audit_artifact_without_stale_doc_gate"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.3",
            statement=(
                "AC traceability reporting distinguishes real test references from "
                "_ac_stubs and trivial placeholder assertions (Was EPIC-008 "
                "AC8.13.35)."
            ),
            test=(
                "tests/tooling/test_check_ac_traceability.py"
                "::test_classifies_placeholder_assertion"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.4",
            statement=(
                "AC traceability fails mandatory ACs that are covered only by "
                "_ac_stubs (Was EPIC-008 AC8.13.37)."
            ),
            test=(
                "tests/tooling/test_check_ac_traceability.py"
                "::test_placeholder_and_stub_refs_do_not_count_as_real_coverage"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.5",
            statement=(
                "Critical proof matrix fails when a core product proof path is backed "
                "only by broad or reference-only AC strings (Was EPIC-008 AC8.13.41)."
            ),
            test=(
                "tests/tooling/test_check_critical_proof_matrix.py"
                "::test_AC8_14_1_critical_proof_matrix_reports_duplicate_proof_ids"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.6",
            statement=(
                "Critical proof matrix validates the closed macro outcome set from "
                "README through owner EPICs and E2E proof anchors (Was EPIC-008 "
                "AC8.13.50)."
            ),
            test=(
                "tests/tooling/test_check_critical_proof_matrix.py"
                "::test_AC8_13_50_macro_outcome_contract_rejects_drift"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.7",
            statement=(
                "Critical proof matrix fails when README macro outcomes, matrix "
                "outcomes, or owner EPIC reverse declarations drift (Was EPIC-008 "
                "AC8.13.54)."
            ),
            test=(
                "tests/tooling/test_check_critical_proof_matrix.py"
                "::test_AC8_13_54_macro_contract_requires_owner_epic_reverse_declarations"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.8",
            statement=(
                "E2E EPIC traceability fails E2E-root test functions missing "
                "function-level EPIC IDs or project EPICs without E2E owners (Was "
                "EPIC-008 AC8.13.68)."
            ),
            test=(
                "tests/tooling/test_check_e2e_epic_traceability.py"
                "::test_AC8_13_68_discovery_handles_missing_roots_and_external_paths"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.9",
            statement=(
                "E2E EPIC traceability fails README EPIC map drift and unclassified "
                "E2E-like assets outside declared roots (Was EPIC-008 AC8.13.70)."
            ),
            test=(
                "tests/tooling/test_check_e2e_epic_traceability.py"
                "::test_AC8_13_70_classified_non_product_e2e_assets_are_allowed"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.10",
            statement=(
                "Registry-to-EPIC consistency fails active stub or orphan AC entries "
                "instead of silently excluding them (Was EPIC-008 AC8.13.77)."
            ),
            test=(
                "tests/tooling/test_lint_doc_consistency.py"
                "::test_AC8_13_77_active_stub_orphan_fails"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.11",
            statement=(
                "Mandatory AC traceability requires at least one real proof file that "
                "is mapped to a CI-required execution stage (Was EPIC-008 AC8.13.78)."
            ),
            test=(
                "tests/tooling/test_check_ac_traceability.py"
                "::test_AC8_13_78_ci_required_real_refs_cover_mandatory_gate"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.12",
            statement=(
                "AC coverage analysis supports no-write and stale-report check modes "
                "for local verification (Was EPIC-008 AC8.13.80)."
            ),
            test=(
                "tests/tooling/test_analyze_test_ac_coverage.py"
                "::test_AC8_13_80_check_mode_fails_stale_report"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.13",
            statement=(
                "AC traceability gate and uploaded audit builder consume the same "
                "SSOT test-surface definition, including frontend Playwright tests "
                "(Was EPIC-008 AC8.13.124)."
            ),
            test=(
                "tests/tooling/test_schema_quality_contract.py"
                "::test_AC8_13_124_traceability_gate_and_audit_builder_share_test_surface"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.14",
            statement=(
                "The AC-index gate's PROTECTION dashboard reports mandatory-AC "
                "coverage as per-type counts (has_real_ref / has_proof / has_score / "
                "has_mirror), never conflating L1 reference presence with behavioral "
                "proof, so a passing gate cannot be read as misleading behavioral "
                "assurance (re-anchored from the retired standalone traceability "
                "report) (Was EPIC-008 AC8.13.135)."
            ),
            test=(
                "tests/tooling/test_ac_index_consistency.py"
                "::test_AC8_13_135_protection_dashboard_separates_reference_from_behavioral"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.15",
            statement=(
                "The AC-score ratchet baseline is a PERSISTED ratchet stored "
                "conflict-free as sorted, one-AC-per-line JSONL with a merge=union "
                "gitattribute, loading into the same in-memory shape the ratchet uses "
                "\u2014 and the ratchet still fails on regression, missing evidence, or "
                "non-pass code (the derived aggregate views it once sat beside are "
                "now covered by AC8.13.139) (Was EPIC-008 AC8.13.138)."
            ),
            test=(
                "tests/tooling/test_proof_index_architecture.py"
                "::test_AC8_13_138_baseline_is_sorted_jsonl_with_union_merge"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.16",
            statement=(
                "The cross-cutting proof/vision/status indexes are unified onto ONE "
                "AC-keyed graph (common/testing/ac_graph.py) built from sharded "
                "sources (EPIC docs, @ac_proof decorators, vision.md, "
                "critical-proof-outcomes.yaml, the JSONL ratchet); the critical-proof "
                "matrix, vision-proof matrix, and README EPIC-status table are "
                "DERIVED on demand and never committed-materialized; and "
                "tools/check_ac_index.py is exactly TWO gates \u2014 Gate A INTEGRITY "
                "(check_integrity, hard: every AC is managed/enumerated with a "
                "protection record AND no dangling reference \u2014 every @ac_proof "
                "resolves to a real test + real AC, every vision item with an owner "
                "EPIC backs an AC, every macro outcome's proof_ids resolve, every "
                "mandatory active AC has a real test reference, with the "
                "per-edge-type messages preserved verbatim) and Gate B PROTECTION "
                "RATCHET (see AC8.13.140) \u2014 instead of N byte-compares (Was EPIC-008 "
                "AC8.13.139)."
            ),
            test=(
                "tests/tooling/test_ac_index_consistency.py"
                "::test_AC8_13_139_gate_passes_on_consistent_tree"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.17",
            statement=(
                "Gate B (PROTECTION RATCHET) of tools/check_ac_index.py is monotonic, "
                "per-type and conflict-safe: an AC with an all-empty protection "
                'record is still "managed" (managed = present in the structure, not '
                "that it has any test); part 1 is the per-AC behavioural-score floor "
                "(ac-score-baseline.jsonl, merge=union, unchanged); part 2 is a "
                "per-type COUNT floor (docs/ssot/protection-floor.json) where the "
                "current count of mandatory active ACs at each type (has_real_ref, "
                "has_proof, has_score, has_mirror) must be >= the committed floor \u2014 "
                "adding protection only RAISES the current count and passes without "
                "editing the floor file, the default all-zero/missing floor is valid, "
                "and floors are raised only by the explicit --update-floor action so "
                "protection-adding PRs never touch the file (Was EPIC-008 "
                "AC8.13.140)."
            ),
            test=(
                "tests/tooling/test_ac_index_consistency.py"
                "::test_AC8_13_140_every_ac_managed_with_empty_protection_passes"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.acgates.18",
            statement=(
                "The AC-index gate is OPERATIONALLY exactly TWO CI gates: the former "
                "standalone CI-stage traceability contract "
                "(common.testing.check_ac_traceability.run_traceability: a mandatory "
                "active AC must resolve to a real test reference in a CI-REQUIRED "
                "execution stage per docs/ssot/test-execution-matrix.yaml, with the "
                "placeholder-only/stub-only/unexecuted-only/missing classifications) "
                "and critical-proof contract "
                "(common.testing.check_critical_proof_matrix.validate_matrix_contract: "
                "per-proof trust_mode/mirror/required_markers/scope/ci_tier + "
                "manual_gate evidence + macro-outcome shape contract) gate STEPS are "
                "RETIRED as separate CI steps; their logic is FOLDED into "
                "check_ac_index's Gate A INTEGRITY (check_repo_contracts) by "
                "importing those modules as LIBRARIES (no reimplementation, verbatim "
                "messages), so every failure they caught still fails the single gate, "
                "the index gate runs ONCE (lint job, not duplicated in "
                "ac-traceability), and no CI job name / required status context is "
                "renamed (Was EPIC-008 AC8.13.141)."
            ),
            test=(
                "tests/tooling/test_two_gate_consolidation.py"
                "::test_AC8_13_141_green_tree_old_gates_and_consolidated_agree"
            ),
            priority="P1",
            status="done",
        ),
        # ── group gate-inventory: gate inventory & proof-execution
        # model (was EPIC-008 AC8.13 subset), migration closeout, #1663
        # / #1718 ──
        ACRecord(
            id="AC-testing.gate-inventory.1",
            statement=(
                "CI simplification keeps a transitional gate inventory where every "
                "workflow job has exactly one proof stage and one task_category; the "
                "inventory matches live workflow jobs and finish.needs, rejects "
                "legacy category keys, and records resolved duplicate cleanups so "
                "cleanup PRs do not leave both old and new entrances behind (Was "
                "EPIC-008 AC8.13.142)."
            ),
            test=(
                "tests/tooling/test_ci_gate_inventory.py"
                "::test_AC8_13_142_ci_gate_inventory_uses_stage_and_task_category_per_job"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-testing.gate-inventory.2",
            statement=(
                "AC is the only coverage key for CI proof placement: @ac_proof "
                "remains backward compatible while each proof edge can carry "
                "execution metadata as proof(name, stage, task_category), where stage "
                "and task_category are proof attributes rather than identity keys and "
                "remain separate from authority tier / proof_kind (Was EPIC-008 "
                "AC8.13.150)."
            ),
            test=(
                "tests/tooling/test_ac_proof_execution_model.py"
                "::test_AC8_13_150_ac_proof_execution_model_is_ac_keyed_and_backward_compatible"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-testing.gate-inventory.3",
            statement=(
                "CI gate inventory vocabulary is shared with the AC proof execution "
                "helper: top-level stages and task_categories match "
                "common.testing.ac_proof_execution exactly, so docs, runtime proof "
                "metadata, and inventory contracts cannot drift independently (Was "
                "EPIC-008 AC8.13.151)."
            ),
            test=(
                "tests/tooling/test_ci_gate_inventory.py"
                "::test_AC8_13_151_ci_gate_inventory_uses_shared_proof_execution_vocabulary"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-testing.gate-inventory.4",
            statement=(
                "The staging AI/OCR corpus gate body lives once in a reusable "
                "staging-ai-ocr-gate.yml (workflow_call) consumed by both the inline "
                "staging deploy chain and the manual staging-ai-ocr-gate dispatch; "
                "the two entrances are uses: callers that differ only by a blocking "
                "input (record-only vs fail-fast) plus checkout/expected_sha, the "
                "duplicated job body is removed, and the cleanup is recorded in the "
                "gate inventory (Was EPIC-008 AC8.13.153)."
            ),
            test=(
                "tests/tooling/test_ci_gate_inventory.py"
                "::test_AC8_13_153_staging_ai_ocr_gate_is_a_single_reusable_workflow"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-testing.gate-inventory.5",
            statement=(
                "The production release line (dry-run, deploy) is split out of "
                "deploy.yml into a manual-dispatch-only release.yml with a "
                "production-release-<version_ref> concurrency group "
                "(cancel-in-progress: false) so two prod releases never run "
                "concurrently; deploy.yml keeps staging deploy and tag-push promote, "
                "and the workflow contract plus gate inventory track the new file and "
                "re-homed job ids (Was EPIC-008 AC8.13.154)."
            ),
            test=(
                "tests/tooling/test_ci_gate_inventory.py"
                "::test_AC8_13_154_production_release_line_lives_in_release_yml"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-testing.gate-inventory.6",
            statement=(
                "The former app-side reclaim split is retired: preview.yml#cleanup "
                "now dispatches a preview-teardown signal to infra2 (which owns the "
                "1:1 reclaim via preview-teardown.yml + the hourly preview-leak-check "
                "fallback), and maintenance.yml#cleanup is GHCR-image-pruning only; "
                "the pr_preview_cleanup_event_vs_scheduled inventory entry records "
                "this retired state, not a keep_separate reclaim split (Was EPIC-008 "
                "AC8.13.155)."
            ),
            test=(
                "tests/tooling/test_ci_gate_inventory.py"
                "::test_AC8_13_155_pr_preview_reclaim_is_dispatched_to_infra2"
            ),
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        # ── group governance: governance & doc-consistency gates (was
        # EPIC-008 AC8.13 subset), migration closeout, #1663 / #1718 ──
        ACRecord(
            id="AC-testing.governance.1",
            statement=(
                "Remaining delivery-engine optimizations are captured in a tracked "
                "project recommendation note (Was EPIC-008 AC8.13.47)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_47_delivery_engine_recommendations_are_tracked"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.governance.2",
            statement=(
                "Coverage threshold documentation links to code-owned thresholds "
                "instead of copying mutable numeric values (Was EPIC-008 AC8.13.81)."
            ),
            test=(
                "tests/tooling/test_lint_doc_consistency.py"
                "::test_AC8_13_81_doc_can_reference_code_owned_threshold_without_number"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.governance.3",
            statement=(
                "CI/CD documentation separates environment taxonomy from pipeline "
                "stages and declares the sparse env x stage execution matrix (Was "
                "EPIC-008 AC8.13.94)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_94_env_and_pipeline_stage_contract_is_documented"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.governance.4",
            statement=(
                "Local verification guidance defaults to affected fast tests and "
                "defines risk-triggered escalation for high-impact paths (Was "
                "EPIC-008 AC8.13.95)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_95_local_fast_gate_and_escalation_policy_are_documented"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.governance.5",
            statement=(
                "Critical-path timeouts and retries are documented in "
                "docs/ssot/ci-cd.md (Was EPIC-008 AC8.13.118)."
            ),
            test=(
                "tests/tooling/test_post_merge_e2e_gates.py"
                "::test_AC8_13_118_timeouts_and_retries_documented"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.governance.6",
            statement=(
                "Runtime incident response SSOT centralizes service-failure triage "
                "and stability proof ownership, while deployment, observability, "
                "CI/CD, and environment smoke docs link to it instead of duplicating "
                "playbooks (Was EPIC-008 AC8.13.126)."
            ),
            test=(
                "tests/tooling/test_runtime_incident_response_ssot.py"
                "::test_AC8_13_126_runtime_incident_response_ssot_centralizes_triage"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.governance.7",
            statement=(
                "Bottom-up proof exceptions and code-owned surfaces are classified in "
                "docs/ssot/governance-exceptions.yaml with a typed "
                "proof_exceptions/code_owned_surfaces entry (id, owner, reason, "
                "issue), validated by tools/check_governance_exceptions.py, leaving "
                "the legacy SSOT governance exceptions list intact (#524) (Was "
                "EPIC-008 AC8.13.131)."
            ),
            test=(
                "tests/tooling/test_governance_exceptions_registry.py"
                "::test_AC8_13_131_every_classified_entry_links_an_owner_and_issue"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.governance.8",
            statement=(
                "Every test/support file with no AC reference stays classified in "
                "docs/project/traceability-exceptions.md, with no unclassified drift "
                "and no product E2E test parked on the allow-list (#511) (Was "
                "EPIC-008 AC8.13.132)."
            ),
            test=(
                "tests/tooling/test_no_ac_test_classification.py"
                "::test_AC8_13_132_no_unclassified_no_ac_test_files"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.governance.9",
            statement=(
                "Cross-document SSOT concepts (reconciliation thresholds, "
                "reconciliation/confirmation state machines, extraction confidence "
                "tiers, confidence-tier rollup) are registered in "
                "docs/ssot/MANIFEST.yaml with anchored owners backed by explicit <a "
                "id> anchors (#340) (Was EPIC-008 AC8.13.133)."
            ),
            test=(
                "tests/tooling/test_ssot_cross_document_anchors.py"
                "::test_AC8_13_133_concepts_registered_in_manifest_with_anchored_owner"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.governance.10",
            statement=(
                "Consolidated/archived stale docs stay absent and every mkdocs nav "
                "markdown target resolves (no dangling internal links after the "
                "consolidation) (#350) (Was EPIC-008 AC8.13.134)."
            ),
            test=(
                "tests/tooling/test_stale_docs_consolidation.py"
                "::test_AC8_13_134_mkdocs_nav_links_resolve"
            ),
            priority="P1",
            status="done",
        ),
        # ── group secret-scan: content-level secret scanning (was
        # EPIC-008 AC8.13 subset), migration closeout, #1663 / #1718 ──
        ACRecord(
            id="AC-testing.secret-scan.1",
            statement=(
                "A content-level secret scan (gitleaks) runs in both the pre-commit "
                "hooks and the CI lint job (local==CI parity), blocking credential "
                "material by content rather than by filename so .gitignore is not the "
                "only line of defense (Was EPIC-008 AC8.13.136)."
            ),
            test=(
                "tests/tooling/test_secret_scan_gate.py"
                "::test_AC8_13_136_gitleaks_runs_in_precommit_and_ci"
            ),
            priority="P0",
            status="done",
        ),
        # ── group toolchain: toolchain, bootstrap & CLI entry points
        # (was EPIC-008 AC8.13 subset), migration closeout, #1663 /
        # #1718 ──
        ACRecord(
            id="AC-testing.toolchain.1",
            statement=(
                "Runtime and container versions stay aligned across local, CI, and "
                "Docker environments (Was EPIC-008 AC8.13.39)."
            ),
            test=(
                "tests/tooling/test_toolchain_contract.py"
                "::test_AC8_13_39_cli_accepts_explicit_repo_root"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.toolchain.2",
            statement=(
                "Local bootstrap provides one command for runtimes, dependency setup, "
                "pre-commit hooks, and container-runtime diagnostics (Was EPIC-008 "
                "AC8.13.44)."
            ),
            test=(
                "tests/tooling/test_bootstrap_local.py"
                "::test_AC8_13_44_bootstrap_reports_container_runtime_prerequisite"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.toolchain.3",
            statement=(
                "Local verification entry points fail on the same backend format "
                "errors and route make test through the root Moon test command "
                "without hashing the infra submodule gitlink as a file input (Was "
                "EPIC-008 AC8.13.45)."
            ),
            test=(
                "tests/tooling/test_cli_and_dev_servers.py"
                "::test_AC8_13_45_lint_backend_format_check_is_required"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.toolchain.4",
            statement=(
                "Common owns SSOT, config and CI contracts, coverage policy, and "
                "isolation helpers; command entry points and tool-owned "
                "implementations live in tools/; PR CI avoids optional Moon bootstrap "
                "for heavy gates that run direct pytest or npm commands, with Moon "
                "availability covered as static config contracts (Was EPIC-008 "
                "AC8.13.53)."
            ),
            test=(
                "tests/tooling/test_common_tooling_modules.py"
                "::test_AC8_13_53_common_coverage_component_is_a_governed_source_root"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.toolchain.5",
            statement=(
                "Coverage command entry points run from tools/; the shared policy "
                "stays in common/meta/extension/coverage/policy.py, and command "
                "implementations live under tools/_lib/coverage/ (Was EPIC-008 "
                "AC8.13.56)."
            ),
            test=(
                "tests/tooling/test_common_tooling_modules.py"
                "::test_AC8_13_56_coverage_tools_delegate_to_common_implementations"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.toolchain.6",
            statement=(
                "SSOT and AC command entry points run from tools/ while shared "
                "implementations live in the packages that own them (common/testing/, "
                "common/meta/extension/, common/platform/); the residual common/ssot/ "
                "generator escape hatch is retired (Was EPIC-008 AC8.13.57)."
            ),
            test=(
                "tests/tooling/test_common_tooling_modules.py"
                "::test_AC8_13_57_ssot_tools_delegate_to_common_implementations"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.toolchain.7",
            statement=(
                "CI and toolchain command entry points run from tools/; reusable "
                "contracts live in the packages that own them (common/runtime/, "
                "common/testing/, common/meta/extension/), while report and shell "
                "command implementations live under tools/_lib/ (Was EPIC-008 "
                "AC8.13.58)."
            ),
            test=(
                "tests/tooling/test_common_tooling_modules.py"
                "::test_AC8_13_58_ci_tools_delegate_to_common_implementations"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.toolchain.8",
            statement=(
                "Config validation command entry points run from tools/ while shared "
                "implementations live under apps/backend/src/runtime/extension/ "
                "(moved from common/config/ when that package folded into runtime, "
                "#1669) (Was EPIC-008 AC8.13.59)."
            ),
            test=(
                "tests/tooling/test_common_tooling_modules.py"
                "::test_AC8_13_59_config_validation_tools_delegate_to_common_implementations"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.toolchain.9",
            statement=(
                "Local E2E command routing distinguishes root deployment E2E from "
                "backend Tier-1 API E2E (Was EPIC-008 AC8.13.79)."
            ),
            test=(
                "tests/tooling/test_cli_and_dev_servers.py"
                "::test_AC8_13_79_cmd_test_backend_e2e_route"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.toolchain.10",
            statement=(
                "Frontend local and CI gates run full TypeScript checking, including "
                "tests, instead of relying only on Next production build type checks "
                "(Was EPIC-008 AC8.13.99)."
            ),
            test=(
                "tests/tooling/test_frontend_typecheck_contract.py"
                "::test_AC8_13_99_frontend_typecheck_is_a_required_gate"
            ),
            priority="P0",
            status="done",
        ),
        # ── group schema: schema/migration proof lanes (was EPIC-008
        # AC8.13 subset), migration closeout, #1663 / #1718 ──
        ACRecord(
            id="AC-testing.schema.1",
            statement=(
                "PR CI runs a schema migration contract against ephemeral Postgres "
                "with alembic upgrade head, alembic check, uploaded context, and "
                "finish aggregation (Was EPIC-008 AC8.13.121)."
            ),
            test=(
                "tests/tooling/test_schema_quality_contract.py"
                "::test_AC8_13_121_pr_ci_runs_schema_migration_contract"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.schema.2",
            statement=(
                "Backend schema drift guard no longer treats an out-of-date Alembic "
                "target or missing CLI as success; PR CI schema-migrations owns hard "
                "proof (Was EPIC-008 AC8.13.122)."
            ),
            test=(
                "tests/tooling/test_schema_quality_contract.py"
                "::test_AC8_13_122_schema_drift_guard_does_not_accept_outdated_targets"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.schema.3",
            statement=(
                "Schema guardrails scan the real apps/backend/migrations/versions "
                "directory instead of a test-local path (Was EPIC-008 AC8.13.123)."
            ),
            test=(
                "tests/tooling/test_schema_quality_contract.py"
                "::test_AC8_13_123_schema_guardrails_scan_real_migration_directory"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.schema.4",
            statement=(
                "Backend business persistence has a production-faithful Alembic-built "
                "proof lane that keeps user foreign keys intact while exercising a "
                "representative accounting write/read path (Was EPIC-008 AC8.13.127)."
            ),
            test=(
                "apps/backend/tests/integration/test_production_faithful_business_persistence.py"
                "::test_AC8_13_127_alembic_business_persistence_keeps_user_fk_contract"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.schema.5",
            statement=(
                "Detached user_id=uuid4() owner shortcuts in DB-backed backend tests "
                "are counted and cannot grow without an explicit budget update (Was "
                "EPIC-008 AC8.13.128)."
            ),
            test=(
                "tests/tooling/test_detached_owner_guard.py"
                "::test_AC8_13_128_budget_fails_on_growth"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.schema.6",
            statement=(
                "Testing SSOT distinguishes fast create_all() fixtures, PR Alembic "
                "schema proof, and the production-faithful backend business "
                "persistence lane (Was EPIC-008 AC8.13.129)."
            ),
            test=(
                "tests/tooling/test_detached_owner_guard.py"
                "::test_AC8_13_129_schema_docs_distinguish_fast_fixture_and_production_faithful_lane"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.schema.7",
            statement=(
                "The detached-owner guard counts only persisted (db.add/db.add_all) "
                "user_id=uuid4() rows \u2014 the real foreign-key risk \u2014 excluding "
                "transient in-memory and service-argument uses, collapsing the "
                "historically-inflated budget to the persisted rows (Was EPIC-008 "
                "AC8.13.130)."
            ),
            test=(
                "tests/tooling/test_detached_owner_guard.py"
                "::test_AC8_13_130_counts_only_persisted_detached_owners"
            ),
            priority="P1",
            status="done",
        ),
        # ── group lifecycle: test lifecycle & namespace isolation (was
        # EPIC-008 AC8.13.69 + EPIC-016 AC16.13), migration closeout,
        # #1663 / #1718 ──
        ACRecord(
            id="AC-testing.lifecycle.1",
            statement=(
                "Local test lifecycle binds namespaced infra to ephemeral host ports "
                "so parallel branches do not collide (Was EPIC-008 AC8.13.69)."
            ),
            test=(
                "apps/backend/tests/unit/infra/test_test_lifecycle.py"
                "::test_namespaced_infra_uses_ephemeral_host_ports"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-testing.lifecycle.2",
            statement=(
                "test_lifecycle \u2014 sanitize_namespace normalizes branch/workspace "
                "names (Was EPIC-016 AC16.13.1)."
            ),
            test=(
                "tests/tooling/test_lifecycle_and_pdf_scripts.py"
                "::test_AC16_13_1_sanitize_namespace_normalization"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.lifecycle.3",
            statement=(
                "test_lifecycle \u2014 get_namespace honors BRANCH_NAME and optional "
                "WORKSPACE_ID (Was EPIC-016 AC16.13.2)."
            ),
            test=(
                "tests/tooling/test_lifecycle_and_pdf_scripts.py"
                "::test_AC16_13_2_get_namespace_from_branch_and_workspace"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.lifecycle.4",
            statement=(
                "test_lifecycle \u2014 get_namespace falls back to git branch plus path "
                "hash when env vars absent (Was EPIC-016 AC16.13.3)."
            ),
            test=(
                "tests/tooling/test_lifecycle_and_pdf_scripts.py"
                "::test_AC16_13_3_get_namespace_from_git_and_path_hash"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.lifecycle.5",
            statement=(
                "test_lifecycle \u2014 get_test_db_name and get_s3_bucket format names "
                "deterministically (Was EPIC-016 AC16.13.4)."
            ),
            test=(
                "tests/tooling/test_lifecycle_and_pdf_scripts.py"
                "::test_AC16_13_4_name_helpers"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.lifecycle.6",
            statement=(
                "test_lifecycle \u2014 load_active_namespaces returns [] on missing or "
                "corrupted tracker file (Was EPIC-016 AC16.13.5)."
            ),
            test=(
                "tests/tooling/test_lifecycle_and_pdf_scripts.py"
                "::test_AC16_13_5_load_active_namespaces_missing_and_corrupt"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.lifecycle.7",
            statement=(
                "test_lifecycle \u2014 register_namespace and unregister_namespace update "
                "active namespace tracker (Was EPIC-016 AC16.13.6)."
            ),
            test=(
                "tests/tooling/test_lifecycle_and_pdf_scripts.py"
                "::test_AC16_13_6_register_unregister_namespace"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.lifecycle.8",
            statement=(
                "test_lifecycle \u2014 get_container_runtime honors CONTAINER_RUNTIME, "
                "otherwise detects podman/docker and returns None when absent (Was "
                "EPIC-016 AC16.13.7)."
            ),
            test=(
                "tests/tooling/test_lifecycle_and_pdf_scripts.py"
                "::test_AC16_13_7_get_container_runtime"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.lifecycle.9",
            statement=(
                "test_lifecycle \u2014 is_db_ready returns false on pg_isready subprocess "
                "failure (Was EPIC-016 AC16.13.8)."
            ),
            test=(
                "tests/tooling/test_lifecycle_and_pdf_scripts.py"
                "::test_AC16_13_8_is_db_ready_handles_failure"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.lifecycle.10",
            statement=(
                "test_lifecycle \u2014 cleanup_worker_databases skips invalid namespace "
                "values (Was EPIC-016 AC16.13.9)."
            ),
            test=(
                "tests/tooling/test_lifecycle_and_pdf_scripts.py"
                "::test_AC16_13_9_cleanup_worker_databases_skips_invalid_namespace"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.lifecycle.11",
            statement=(
                "test_lifecycle \u2014 cleanup_worker_databases drops valid worker DB "
                "names and skips invalid names (Was EPIC-016 AC16.13.10)."
            ),
            test=(
                "tests/tooling/test_lifecycle_and_pdf_scripts.py"
                "::test_AC16_13_10_cleanup_worker_databases_drops_valid_and_skips_invalid"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.lifecycle.12",
            statement=(
                "test_lifecycle \u2014 _get_changed_files maps backend python paths into "
                "module import names (Was EPIC-016 AC16.13.11)."
            ),
            test=(
                "tests/tooling/test_lifecycle_and_pdf_scripts.py"
                "::test_AC16_13_11_get_changed_files_maps_backend_modules"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-testing.lifecycle.13",
            statement=(
                "generate_test_pdfs \u2014 generate_statement writes table rows and "
                "closing balance from Decimal transactions (Was EPIC-016 AC16.13.12)."
            ),
            test=(
                "tests/tooling/test_lifecycle_and_pdf_scripts.py"
                "::test_AC16_13_12_generate_statement_builds_pdf_rows"
            ),
            priority="P1",
            status="done",
        ),
        # ── group preflight: diff-aware pre-push dispatcher tiering
        # (#1810 G-static-parity) ──
        ACRecord(
            id="AC-testing.preflight.1",
            statement=(
                "Preflight check tiering composes with the diff-glob selection: "
                "--tier=static keeps exactly the seconds-level static gates "
                "matching the diff and drops the heavy suite gates, while the "
                "default full tier preserves the exact pre-tier selection, so "
                "every static blocking PR gate is runnable locally in seconds "
                "via one command (#1810 G-static-parity)."
            ),
            test=(
                "tests/tooling/test_preflight.py"
                "::test_AC_testing_preflight_1_static_tier_composes_with_glob_selection"
            ),
            priority="P1",
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
