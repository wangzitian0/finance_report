"""The ``testing`` package's machine-checkable :class:`PackageContract`.

``testing`` is a ``kernel`` leaf: test/fixture-scoped capability code reused
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
``common/testing/generate_ac_registry.py`` sources them directly from this
contract, same as ``counter``. ``roadmap`` groups 1-8 migrated from EPIC-009
(PDF fixture generation, the leading "9" dropped, group/seq preserved:
``AC9.<g>.<s>`` -> ``AC-testing.<g>.<s>``).

EPIC-023's cassette-layer ACs (AC23.5/AC23.6/AC23.7, plus the graded-eval
AC23.8) deliberately do NOT migrate here, even though AC23.5-.7 carry a
``{tier:CODE-ONLY}`` annotation in EPIC-023 prose: this package's own
governance gate (``common/authority/check_authority_reconcile.py``) DETECTS a
package's tier from what its roadmap-AC tests actually exercise, and
``common/authority/authority_classifier.py`` classifies *any* test that
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

from common.meta.package_contract import ACRecord, Invariant, Kind, PackageContract, Unit

CONTRACT = PackageContract(
    name="testing",
    klass="kernel",
    status="active",
    # Deterministic test/fixture helpers, no LLM in the package: CODE-ONLY.
    tier="CODE-ONLY",
    depends_on=["money"],
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
            statement=("Mari generator generates interest section (Was EPIC-009 AC9.6.4)."),
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
            statement=("Main script supports --source parameter (Was EPIC-009 AC9.7.1)."),
            test="tests/tooling/test_pdf_fixture_tooling_coverage.py::test_AC9_7_1_AC9_7_2_main_generates_selected_source",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-testing.7.2",
            statement=("Main script supports --output parameter (Was EPIC-009 AC9.7.2)."),
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
            statement=("Validator rejects missing or drifting real-format contracts (Was EPIC-009 AC9.8.2)."),
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
    ],
)
