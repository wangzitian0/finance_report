"""Tests for tools/lint_doc_consistency.py.

Covers all six checks plus helper functions: parse_vision_anchors,
parse_epic_anchor, load_registry_acs, is_deprecated, is_stub,
collect_ac_refs_in_epics, collect_ac_refs_in_tests,
check_epic_anchors, check_orphan_vision_anchors, check_registry_to_epic,
check_epic_to_registry, check_registry_to_tests, check_test_id_epic_alignment,
and main().
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from common.testing import lint_doc_consistency as ldc


def test_AC16_25_1_playwright_specs_are_traceability_test_roots() -> None:
    """AC16.25.1: Frontend Playwright mobile specs count as AC proof."""
    playwright_root = ldc.REPO_ROOT / "apps" / "frontend" / "playwright"

    assert playwright_root in ldc.TEST_ROOTS
    assert any(
        base == playwright_root and "**/*.spec.ts" in patterns
        for base, patterns in ldc.NO_AC_SCAN_TARGETS
    )


def test_mkdocs_nav_coverage_passes_for_public_docs() -> None:
    """Public SSOT, governance, API, and active EPIC docs are MkDocs-reachable."""
    assert ldc.check_mkdocs_nav_coverage() == []


def test_mkdocs_nav_coverage_reports_missing_required_doc(tmp_path) -> None:
    mkdocs = tmp_path / "mkdocs.yml"
    mkdocs.write_text(
        """
nav:
  - Home: index.md
  - Technical Docs:
      - Architecture: ssot/README.md
""",
        encoding="utf-8",
    )

    violations = ldc.check_mkdocs_nav_coverage(mkdocs)

    assert violations
    assert any("docs/reference/api.md" in violation.message for violation in violations)


def test_mkdocs_nav_coverage_reports_missing_config(tmp_path) -> None:
    missing = tmp_path / "mkdocs.yml"

    violations = ldc.check_mkdocs_nav_coverage(missing)

    assert len(violations) == 1
    assert violations[0].check == "check11_mkdocs_nav_coverage"
    assert "missing MkDocs config" in violations[0].message


def test_collect_mkdocs_nav_docs_preserves_docs_prefixed_paths(tmp_path) -> None:
    mkdocs = tmp_path / "mkdocs.yml"
    mkdocs.write_text(
        """
nav:
  - Agents: docs/agents/orchestration.md
  - SSOT: ssot/README.md
""",
        encoding="utf-8",
    )

    docs = ldc.collect_mkdocs_nav_docs(mkdocs)

    assert "docs/agents/orchestration.md" in docs
    assert "docs/ssot/README.md" in docs


def test_module_readmes_are_thin_passes_for_repo() -> None:
    """Module README files remain pointers to SSOT owners."""
    assert ldc.check_module_readmes_are_thin() == []


def test_module_readmes_are_thin_reports_duplicate_sections(tmp_path) -> None:
    readme = tmp_path / "module" / "README.md"
    readme.parent.mkdir()
    readme.write_text(
        "# Module\n\n## API Endpoints\n\n| Method | Path |\n|---|---|\n",
        encoding="utf-8",
    )

    with (
        mock.patch.object(ldc._base, "REPO_ROOT", tmp_path),
        mock.patch.object(ldc._parsing, "THIN_README_LIMITS", {"module/README.md": 4}),
    ):
        violations = ldc.check_module_readmes_are_thin()

    assert len(violations) == 2
    assert any("exceeds 4" in violation.message for violation in violations)
    assert any("## API Endpoints" in violation.message for violation in violations)


def test_AC14_1_7_generated_analysis_snapshots_are_absent(tmp_path) -> None:
    """AC14.1.7: Generated analysis snapshots are not checked into docs/project."""
    snapshot = tmp_path / "docs" / "project" / "test-ac-coverage-report.md"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("# generated\n", encoding="utf-8")

    violations = ldc.check_generated_analysis_snapshots_absent((snapshot,))

    assert len(violations) == 1
    assert violations[0].check == "check13_generated_analysis_snapshots_absent"


def test_AC14_1_7_generated_analysis_snapshots_absent_passes(tmp_path) -> None:
    """AC14.1.7: Missing generated snapshots are the expected repository state."""
    snapshot = tmp_path / "docs" / "project" / "test-ac-coverage-report.md"

    assert ldc.check_generated_analysis_snapshots_absent((snapshot,)) == []


def test_AC14_1_8_reconciliation_thresholds_are_code_owned(tmp_path) -> None:
    """AC14.1.8: Reconciliation threshold prose points to code/config owners."""
    doc = tmp_path / "reconciliation.md"
    doc.write_text(
        """
### Reconciliation Thresholds

Runtime values are owned by apps/backend/config/reconciliation.yaml and
apps/backend/src/services/reconciliation.py through DEFAULT_CONFIG and
load_reconciliation_config. Overrides use RECONCILIATION_AUTO_ACCEPT_THRESHOLD
and RECONCILIATION_REVIEW_THRESHOLD.
""",
        encoding="utf-8",
    )

    assert ldc.check_reconciliation_thresholds_are_code_owned(doc) == []

    doc.write_text(
        "This table is the single authoritative definition of reconciliation score thresholds.",
        encoding="utf-8",
    )
    violations = ldc.check_reconciliation_thresholds_are_code_owned(doc)

    assert violations
    assert any("single authority" in violation.message for violation in violations)


def test_AC14_1_8_reconciliation_thresholds_report_unreadable_doc() -> None:
    """AC14.1.8: Missing reconciliation SSOT fails closed."""
    missing = Path("/definitely/missing/reconciliation.md")

    violations = ldc.check_reconciliation_thresholds_are_code_owned(missing)

    assert len(violations) == 1
    assert violations[0].check == "check14_reconciliation_thresholds_code_owned"
    assert "cannot read file" in violations[0].message


def test_AC14_1_10_frontend_raw_fetch_is_limited_to_api_wrapper(tmp_path) -> None:
    """AC14.1.10: Frontend raw fetch is limited to the API wrapper."""
    src = tmp_path / "apps" / "frontend" / "src"
    api = src / "lib" / "api.ts"
    page = src / "app" / "page.tsx"
    test_file = src / "__tests__" / "api.test.ts"
    api.parent.mkdir(parents=True)
    page.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    api.write_text("export const apiFetch = () => fetch('/api/test')\n", encoding="utf-8")
    page.write_text("export const load = () => fetch('/api/accounts')\n", encoding="utf-8")
    test_file.write_text("expect(fetch).toBeDefined()\n", encoding="utf-8")

    violations = ldc.check_frontend_raw_fetch_usage(src, {api})

    assert len(violations) == 1
    assert "app/page.tsx:1" in violations[0].message


def test_AC14_1_10_frontend_raw_fetch_missing_source_root_passes(tmp_path) -> None:
    """AC14.1.10: Missing optional frontend source root has no raw fetch violations."""
    assert ldc.check_frontend_raw_fetch_usage(tmp_path / "missing", set()) == []


def test_AC14_1_10_frontend_raw_fetch_unreadable_file_is_skipped(tmp_path) -> None:
    """AC14.1.10: Raw fetch scanner skips files it cannot read."""
    src = tmp_path / "apps" / "frontend" / "src"
    page = src / "app" / "page.tsx"
    page.parent.mkdir(parents=True)
    page.write_text("fetch('/api/accounts')\n", encoding="utf-8")

    with mock.patch.object(Path, "read_text", side_effect=OSError("blocked")):
        violations = ldc.check_frontend_raw_fetch_usage(src, set())

    assert violations == []


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

MINIMAL_VISION_MD = """\
# Vision

<a id="decision-1-accounting"></a>
Some text.

<a id="decision-2-reconciliation"></a>
More text.
"""

EPIC_WITH_ANCHOR = """\
# EPIC-001 Phase 0 Setup

> **Vision Anchor**: `decision-1-accounting`

## ACs

AC1.1.1 setup complete
"""

EPIC_MISSING_ANCHOR = """\
# EPIC-002 Double Entry

## ACs

AC2.1.1 balanced entries
"""

EPIC_WRONG_ANCHOR = """\
# EPIC-003 Extraction

> **Vision Anchor**: `nonexistent-slug`

## ACs

AC3.1.1 upload PDF
"""

SAMPLE_REGISTRY_YAML = """\
version: '1.0'
groups:
  AC1:
    AC1.1:
      - id: AC1.1.1
        epic: 1
        epic_name: phase0-setup
        description: 'System is deployed'
        mandatory: true
      - id: AC1.1.2
        epic: 1
        epic_name: phase0-setup
        description: 'Health check passes'
        mandatory: false
  AC2:
    AC2.1:
      - id: AC2.1.1
        epic: 2
        epic_name: double-entry-core
        description: 'Balanced entries stored'
        mandatory: true
        status: deprecated
  AC3:
    AC3.1:
      - id: AC3.1.1
        epic: 3
        epic_name: extraction
        description: 'Upload PDF'
        mandatory: true
        status: stub
"""


# ---------------------------------------------------------------------------
# load_registry_acs
# ---------------------------------------------------------------------------


class TestLoadRegistryAcs:
    def test_loads_entries(self, tmp_path):
        f = tmp_path / "reg.yaml"
        f.write_text(SAMPLE_REGISTRY_YAML)
        acs = ldc.load_registry_acs(f)
        assert len(acs) == 4

    def test_missing_file_returns_empty(self, tmp_path):
        acs = ldc.load_registry_acs(tmp_path / "nonexistent.yaml")
        assert acs == []

    def test_empty_file_returns_empty(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("{}")
        acs = ldc.load_registry_acs(f)
        assert acs == []


# ---------------------------------------------------------------------------
# is_deprecated / is_stub
# ---------------------------------------------------------------------------


class TestIsDeprecated:
    def test_status_deprecated(self):
        assert ldc.is_deprecated({"status": "deprecated"})

    def test_status_Deprecated_case_insensitive(self):
        assert ldc.is_deprecated({"status": "DEPRECATED"})

    def test_deprecated_flag_true(self):
        assert ldc.is_deprecated({"deprecated": True})

    def test_full_strikethrough_description(self):
        assert ldc.is_deprecated({"description": "~~removed behavior~~"})

    def test_not_deprecated(self):
        assert not ldc.is_deprecated({"status": "active"})

    def test_empty_dict(self):
        assert not ldc.is_deprecated({})


class TestIsStub:
    def test_status_stub(self):
        assert ldc.is_stub({"status": "stub"})

    def test_status_STUB_case_insensitive(self):
        assert ldc.is_stub({"status": "STUB"})

    def test_not_stub(self):
        assert not ldc.is_stub({"status": "active"})

    def test_empty_dict(self):
        assert not ldc.is_stub({})


# ---------------------------------------------------------------------------
# parse_vision_anchors
# ---------------------------------------------------------------------------


class TestParseVisionAnchors:
    def test_finds_anchors(self):
        slugs = ldc.parse_vision_anchors(MINIMAL_VISION_MD)
        assert "decision-1-accounting" in slugs
        assert "decision-2-reconciliation" in slugs

    def test_empty_text(self):
        assert ldc.parse_vision_anchors("") == set()

    def test_no_anchors(self):
        assert ldc.parse_vision_anchors("# No anchors here") == set()

    def test_single_quotes(self):
        text = "<a id='my-slug'></a>"
        assert "my-slug" in ldc.parse_vision_anchors(text)

    def test_multiple_anchors(self):
        text = '<a id="a"></a> text <a id="b"></a>'
        slugs = ldc.parse_vision_anchors(text)
        assert slugs == {"a", "b"}


# ---------------------------------------------------------------------------
# parse_epic_anchor
# ---------------------------------------------------------------------------


class TestParseEpicAnchor:
    def test_bold_variant(self):
        text = "> **Vision Anchor**: `my-slug`\n"
        assert ldc.parse_epic_anchor(text) == "my-slug"

    def test_non_blockquote_variant(self):
        text = "**Vision Anchor**: `another-slug`\n"
        assert ldc.parse_epic_anchor(text) == "another-slug"

    def test_simple_blockquote_variant(self):
        text = "> Vision Anchor: `simple-slug`\n"
        assert ldc.parse_epic_anchor(text) == "simple-slug"

    def test_missing_returns_none(self):
        assert ldc.parse_epic_anchor("# EPIC-001\n\nNo anchor here.") is None

    def test_returns_first_match(self):
        text = "> **Vision Anchor**: `first-slug`\n> **Vision Anchor**: `second-slug`"
        assert ldc.parse_epic_anchor(text) == "first-slug"


# ---------------------------------------------------------------------------
# _line_is_ac_annotation
# ---------------------------------------------------------------------------


class TestLineIsAcAnnotation:
    def test_total_ac_ids_line(self):
        assert ldc._line_is_ac_annotation(
            "- Total AC IDs: 52 (AC2.11.1-2.11.3 removed)"
        )

    def test_removed_annotation(self):
        assert ldc._line_is_ac_annotation(
            "*(AC10.2.1 removed - canonical copy is AC12.1.1)*"
        )

    def test_duplicate_annotation(self):
        assert ldc._line_is_ac_annotation("(AC5.1.1 duplicate of AC5.1.2 canonical)")

    def test_normal_line(self):
        assert not ldc._line_is_ac_annotation("AC1.1.1 System is deployed")

    def test_empty_line(self):
        assert not ldc._line_is_ac_annotation("")


# ---------------------------------------------------------------------------
# check_proof_placement_policy
# ---------------------------------------------------------------------------


class TestProofPlacementPolicy:
    def test_policy_passes_with_required_tokens(self, tmp_path):
        doc = tmp_path / "ci-cd.md"
        doc.write_text(
            "\n".join(ldc.PROOF_PLACEMENT_REQUIRED_TOKENS),
            encoding="utf-8",
        )

        assert ldc.check_proof_placement_policy(doc) == []

    def test_policy_fails_when_behavioral_and_environment_split_is_missing(
        self, tmp_path
    ):
        doc = tmp_path / "ci-cd.md"
        doc.write_text("### CI\nNo proof placement policy here.\n", encoding="utf-8")

        violations = ldc.check_proof_placement_policy(doc)

        assert violations
        assert {v.check for v in violations} == {"check7_proof_placement_policy"}
        assert any("Proof Placement Policy" in v.message for v in violations)


# ---------------------------------------------------------------------------
# no-AC test exception allow-list
# ---------------------------------------------------------------------------


class TestNoAcTestExceptions:
    def test_discover_no_ac_test_files_includes_support_files(self, tmp_path):
        tests = tmp_path / "apps" / "backend" / "tests"
        tests.mkdir(parents=True)
        no_ac = tests / "conftest.py"
        no_ac.write_text("import pytest\n")
        with_ac = tests / "test_accounting.py"
        with_ac.write_text('def test_x():\n    """AC1.1.1"""\n    assert True\n')

        result = ldc.discover_no_ac_test_files(((tests, ("**/*.py",)),))

        assert result == [no_ac]

    def test_discover_no_ac_test_files_skips_excluded_paths(self, tmp_path):
        tests = tmp_path / "tests"
        skipped = tests / "node_modules" / "test_generated.py"
        skipped.parent.mkdir(parents=True)
        skipped.write_text("def test_generated():\n    assert True\n", encoding="utf-8")

        result = ldc.discover_no_ac_test_files(((tests, ("**/*.py",)),))

        assert result == []

    def test_discover_no_ac_test_files_skips_unreadable_files(self, tmp_path):
        tests = tmp_path / "tests"
        test_file = tests / "test_unreadable.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("def test_unreadable():\n    assert True\n", encoding="utf-8")

        with mock.patch.object(Path, "read_text", side_effect=OSError("blocked")):
            result = ldc.discover_no_ac_test_files(((tests, ("**/*.py",)),))

        assert result == []

    def test_load_traceability_exception_paths_reads_markdown_code_spans(
        self, tmp_path
    ):
        exceptions = tmp_path / "traceability-exceptions.md"
        exceptions.write_text(
            "| Path | Classification |\n"
            "|---|---|\n"
            "| `tests/conftest.py` | Shared fixtures |\n",
            encoding="utf-8",
        )

        assert "tests/conftest.py" in ldc.load_traceability_exception_paths(exceptions)

    def test_check_no_ac_test_exceptions_passes_when_listed(self, tmp_path):
        test_file = tmp_path / "tests" / "conftest.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("import pytest\n")
        exceptions = tmp_path / "docs" / "project" / "traceability-exceptions.md"
        exceptions.parent.mkdir(parents=True)
        exceptions.write_text("| `tests/conftest.py` | Shared fixtures |\n")

        with mock.patch.object(ldc._base, "REPO_ROOT", tmp_path):
            violations = ldc.check_no_ac_test_exceptions([test_file], exceptions)

        assert violations == []

    def test_check_no_ac_test_exceptions_fails_when_missing(self, tmp_path):
        test_file = tmp_path / "tests" / "test_legacy.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("def test_legacy():\n    assert True\n")
        exceptions = tmp_path / "docs" / "project" / "traceability-exceptions.md"
        exceptions.parent.mkdir(parents=True)
        exceptions.write_text("| `tests/other.py` | Other |\n")

        with mock.patch.object(ldc._base, "REPO_ROOT", tmp_path):
            violations = ldc.check_no_ac_test_exceptions([test_file], exceptions)

        assert len(violations) == 1
        assert violations[0].check == "check8_no_ac_test_exceptions"
        assert "tests/test_legacy.py" in violations[0].message

    def test_e2e_product_test_exception_fails(self, tmp_path):
        exceptions = tmp_path / "docs" / "project" / "traceability-exceptions.md"
        exceptions.parent.mkdir(parents=True)
        exceptions.write_text(
            "| `tests/e2e/test_legacy_flow.py` | EPIC-008 |\n"
            "| `tests/e2e/conftest.py` | Shared fixtures |\n"
            "| `apps/backend/tests/e2e/test_legacy_api.py` | EPIC-008 |\n",
            encoding="utf-8",
        )

        violations = ldc.check_no_e2e_product_test_exceptions(exceptions)

        assert [v.check for v in violations] == [
            "check9_no_e2e_product_test_exceptions",
            "check9_no_e2e_product_test_exceptions",
        ]
        messages = "\n".join(v.message for v in violations)
        assert "tests/e2e/test_legacy_flow.py" in messages
        assert "apps/backend/tests/e2e/test_legacy_api.py" in messages
        assert all("conftest.py" not in v.message for v in violations)

    def test_e2e_product_exception_policy_glob_is_not_a_file(self, tmp_path):
        exceptions = tmp_path / "docs" / "project" / "traceability-exceptions.md"
        exceptions.parent.mkdir(parents=True)
        exceptions.write_text(
            "Policy applies to `tests/e2e/test_*.py` files.\n",
            encoding="utf-8",
        )

        assert ldc.check_no_e2e_product_test_exceptions(exceptions) == []


# ---------------------------------------------------------------------------
# collect_ac_refs_in_epics
# ---------------------------------------------------------------------------


class TestCollectAcRefsInEpics:
    def test_basic_collection(self, tmp_path):
        epic = tmp_path / "EPIC-001.test.md"
        epic.write_text("AC1.1.1 and AC1.1.2 are covered here")
        refs = ldc.collect_ac_refs_in_epics([epic])
        assert "AC1.1.1" in refs
        assert "AC1.1.2" in refs

    def test_annotation_lines_skipped(self, tmp_path):
        epic = tmp_path / "EPIC-001.test.md"
        epic.write_text("- Total AC IDs: 5 (AC2.11.1 removed)\nAC1.1.1 real ref")
        refs = ldc.collect_ac_refs_in_epics([epic])
        assert "AC2.11.1" not in refs
        assert "AC1.1.1" in refs

    def test_unreadable_file_skipped(self, tmp_path):
        epic = tmp_path / "EPIC-001.test.md"
        epic.write_text("AC1.1.1")
        with mock.patch.object(
            Path, "read_text", side_effect=OSError("permission denied")
        ):
            refs = ldc.collect_ac_refs_in_epics([epic])
        assert refs == {}

    def test_multiple_files(self, tmp_path):
        e1 = tmp_path / "EPIC-001.test.md"
        e2 = tmp_path / "EPIC-002.test.md"
        e1.write_text("AC1.1.1")
        e2.write_text("AC1.1.1 AC2.1.1")
        refs = ldc.collect_ac_refs_in_epics([e1, e2])
        assert "EPIC-001.test.md" in refs["AC1.1.1"]
        assert "EPIC-002.test.md" in refs["AC1.1.1"]
        assert "AC2.1.1" in refs


# ---------------------------------------------------------------------------
# collect_ac_refs_in_tests
# ---------------------------------------------------------------------------


class TestCollectAcRefsInTests:
    def test_collects_from_test_file(self, tmp_path):
        tests = tmp_path / "tests"
        tests.mkdir()
        tf = tests / "test_accounting.py"
        tf.write_text("# AC1.1.1\n# AC2.1.1\n")
        with mock.patch.object(ldc._base, "REPO_ROOT", tmp_path):
            refs = ldc.collect_ac_refs_in_tests([tests])
        assert "AC1.1.1" in refs
        assert "AC2.1.1" in refs

    def test_non_test_files_skipped(self, tmp_path):
        tests = tmp_path / "tests"
        tests.mkdir()
        tf = tests / "helpers.py"  # no test_ prefix, no test suffix
        tf.write_text("# AC1.1.1\n")
        refs = ldc.collect_ac_refs_in_tests([tests])
        assert "AC1.1.1" not in refs

    def test_test_ts_suffix_collected(self, tmp_path):
        tests = tmp_path / "tests"
        tests.mkdir()
        tf = tests / "accounting.test.ts"
        tf.write_text("// AC1.1.1\n")
        with mock.patch.object(ldc._base, "REPO_ROOT", tmp_path):
            refs = ldc.collect_ac_refs_in_tests([tests])
        assert "AC1.1.1" in refs

    def test_excluded_dirs_skipped(self, tmp_path):
        tests = tmp_path / "tests"
        tests.mkdir()
        node_modules = tests / "node_modules"
        node_modules.mkdir()
        tf = node_modules / "test_bad.py"
        tf.write_text("# AC1.1.1\n")
        refs = ldc.collect_ac_refs_in_tests([tests])
        assert "AC1.1.1" not in refs

    def test_missing_directory_skipped(self, tmp_path):
        refs = ldc.collect_ac_refs_in_tests([tmp_path / "nonexistent"])
        assert refs == {}

    def test_unreadable_file_skipped(self, tmp_path):
        tests = tmp_path / "tests"
        tests.mkdir()
        tf = tests / "test_x.py"
        tf.write_text("AC1.1.1")
        with mock.patch.object(Path, "read_text", side_effect=OSError("error")):
            refs = ldc.collect_ac_refs_in_tests([tests])
        assert refs == {}


# ---------------------------------------------------------------------------
# check_epic_anchors (check #1)
# ---------------------------------------------------------------------------


class TestCheckEpicAnchors:
    def test_valid_anchor(self, tmp_path):
        epic = tmp_path / "EPIC-001.test.md"
        epic.write_text(EPIC_WITH_ANCHOR)
        vision_anchors = {"decision-1-accounting", "decision-2-reconciliation"}
        violations, epic_to_slug = ldc.check_epic_anchors([epic], vision_anchors)
        assert violations == []
        assert epic_to_slug["EPIC-001.test.md"] == "decision-1-accounting"

    def test_missing_anchor_line(self, tmp_path):
        epic = tmp_path / "EPIC-002.test.md"
        epic.write_text(EPIC_MISSING_ANCHOR)
        violations, epic_to_slug = ldc.check_epic_anchors([epic], {"some-anchor"})
        assert any(v.check == "check1_epic_anchor" for v in violations)
        assert "EPIC-002.test.md" not in epic_to_slug

    def test_slug_not_in_vision(self, tmp_path):
        epic = tmp_path / "EPIC-003.test.md"
        epic.write_text(EPIC_WRONG_ANCHOR)
        violations, _ = ldc.check_epic_anchors([epic], {"decision-1-accounting"})
        assert any("nonexistent-slug" in v.message for v in violations)

    def test_unreadable_file(self, tmp_path):
        epic = tmp_path / "EPIC-001.test.md"
        epic.write_text(EPIC_WITH_ANCHOR)
        with mock.patch.object(Path, "read_text", side_effect=OSError("no access")):
            violations, _ = ldc.check_epic_anchors([epic], {"decision-1-accounting"})
        assert any(v.check == "check1_epic_anchor" for v in violations)


# ---------------------------------------------------------------------------
# check_orphan_vision_anchors (check #2)
# ---------------------------------------------------------------------------


class TestCheckOrphanVisionAnchors:
    def test_no_orphans(self):
        vision_anchors = {"a", "b"}
        epic_to_slug = {"EPIC-001.md": "a", "EPIC-002.md": "b"}
        violations = ldc.check_orphan_vision_anchors(vision_anchors, epic_to_slug)
        assert violations == []

    def test_orphan_detected(self):
        vision_anchors = {"a", "b", "orphan"}
        epic_to_slug = {"EPIC-001.md": "a", "EPIC-002.md": "b"}
        violations = ldc.check_orphan_vision_anchors(vision_anchors, epic_to_slug)
        assert len(violations) == 1
        assert "orphan" in violations[0].message

    def test_multiple_orphans(self):
        violations = ldc.check_orphan_vision_anchors(
            {"a", "b", "c"},
            {"EPIC-001.md": "a"},
        )
        assert len(violations) == 2


# ---------------------------------------------------------------------------
# check_registry_to_epic (check #3)
# ---------------------------------------------------------------------------


class TestCheckRegistryToEpic:
    def test_all_referenced(self):
        acs = [{"id": "AC1.1.1", "mandatory": True}]
        epic_refs = {"AC1.1.1": {"EPIC-001.md"}}
        violations = ldc.check_registry_to_epic(acs, epic_refs)
        assert violations == []

    def test_missing_reference(self):
        acs = [{"id": "AC1.1.1", "mandatory": True}]
        violations = ldc.check_registry_to_epic(acs, {})
        assert len(violations) == 1
        assert "AC1.1.1" in violations[0].message

    def test_deprecated_skipped(self):
        acs = [{"id": "AC1.1.1", "status": "deprecated"}]
        violations = ldc.check_registry_to_epic(acs, {})
        assert violations == []

    def test_strikethrough_deprecated_skipped(self):
        acs = [{"id": "AC1.1.1", "description": "~~removed behavior~~"}]
        violations = ldc.check_registry_to_epic(acs, {})
        assert violations == []

    def test_AC8_13_77_active_stub_orphan_fails(self):
        """AC8.13.77: Active stub registry entries cannot bypass EPIC ownership."""
        acs = [{"id": "AC1.1.1", "status": "stub", "mandatory": False}]
        violations = ldc.check_registry_to_epic(acs, {})
        assert len(violations) == 1
        assert "AC1.1.1" in violations[0].message

    def test_AC8_13_77_deprecated_stub_orphan_is_retained_as_history(self):
        """AC8.13.77: Deprecated historical placeholders do not count as active ACs."""
        acs = [{"id": "AC1.1.1", "status": "deprecated"}]
        violations = ldc.check_registry_to_epic(acs, {})
        assert violations == []

    def test_missing_id_skipped(self):
        acs = [{"epic": 1, "description": "no id field"}]
        violations = ldc.check_registry_to_epic(acs, {})
        assert violations == []


class TestCoverageThresholdDocs:
    def test_AC8_13_81_doc_can_reference_code_owned_threshold_without_number(
        self, tmp_path
    ):
        """AC8.13.81: Coverage threshold docs should link to the code owner."""
        doc = tmp_path / "tdd.md"
        doc.write_text(
            "Backend local coverage threshold is code-owned by "
            "`apps/backend/pyproject.toml` `--cov-fail-under`.\n",
            encoding="utf-8",
        )

        assert ldc.check_code_owned_coverage_threshold_doc(doc) == []

    def test_AC8_13_81_doc_fails_when_backend_threshold_number_is_copied(
        self, tmp_path
    ):
        """AC8.13.81: Mutable backend coverage percentages should not be copied."""
        doc = tmp_path / "tdd.md"
        doc.write_text(
            "Backend pytest keeps a 90% local source-coverage threshold.\n",
            encoding="utf-8",
        )

        violations = ldc.check_code_owned_coverage_threshold_doc(doc)

        assert len(violations) == 1
        assert "code-owned" in violations[0].message


# ---------------------------------------------------------------------------
# check_epic_to_registry (check #4)
# ---------------------------------------------------------------------------


class TestCheckEpicToRegistry:
    def test_all_in_registry(self):
        epic_refs = {"AC1.1.1": {"EPIC-001.md"}}
        registry_ids = {"AC1.1.1"}
        violations = ldc.check_epic_to_registry(epic_refs, registry_ids)
        assert violations == []

    def test_dangling_ac(self):
        epic_refs = {"AC99.1.1": {"EPIC-001.md"}}
        violations = ldc.check_epic_to_registry(epic_refs, set())
        assert len(violations) == 1
        assert "AC99.1.1" in violations[0].message

    def test_multiple_sources_shown(self):
        epic_refs = {"AC99.1.1": {"EPIC-001.md", "EPIC-002.md"}}
        violations = ldc.check_epic_to_registry(epic_refs, set())
        assert violations[0].check == "check4_epic_to_registry"


# ---------------------------------------------------------------------------
# check_registry_to_tests (check #5)
# ---------------------------------------------------------------------------


class TestCheckRegistryToTests:
    def test_all_covered(self):
        acs = [{"id": "AC1.1.1", "mandatory": True}]
        test_refs = {"AC1.1.1": {"apps/backend/tests/test_x.py"}}
        violations = ldc.check_registry_to_tests(acs, test_refs)
        assert violations == []

    def test_missing_test_ref(self):
        acs = [{"id": "AC1.1.1", "mandatory": True}]
        violations = ldc.check_registry_to_tests(acs, {})
        assert len(violations) == 1

    def test_deprecated_skipped(self):
        acs = [{"id": "AC1.1.1", "status": "deprecated", "mandatory": True}]
        violations = ldc.check_registry_to_tests(acs, {})
        assert violations == []

    def test_strikethrough_deprecated_skipped(self):
        acs = [
            {"id": "AC1.1.1", "description": "~~removed behavior~~", "mandatory": True}
        ]
        violations = ldc.check_registry_to_tests(acs, {})
        assert violations == []

    def test_non_mandatory_skipped(self):
        acs = [{"id": "AC1.1.1", "mandatory": False}]
        violations = ldc.check_registry_to_tests(acs, {})
        assert violations == []

    def test_missing_id_skipped(self):
        acs = [{"epic": 1}]
        violations = ldc.check_registry_to_tests(acs, {})
        assert violations == []


# ---------------------------------------------------------------------------
# check_test_id_epic_alignment (check #6)
# ---------------------------------------------------------------------------


class TestCheckTestIdEpicAlignment:
    def test_matching_epic(self):
        acs = [{"id": "AC1.1.1", "epic": 1}]
        test_refs = {"AC1.1.1": {"tests/test_x.py"}}
        violations = ldc.check_test_id_epic_alignment(acs, test_refs)
        assert violations == []

    def test_mismatched_epic(self):
        acs = [{"id": "AC1.1.1", "epic": 2}]  # epic field says 2, but ID says 1
        test_refs = {"AC1.1.1": {"tests/test_x.py"}}
        violations = ldc.check_test_id_epic_alignment(acs, test_refs)
        assert len(violations) == 1
        assert "check6" in violations[0].check

    def test_fixture_exclude_skipped(self):
        # AC1.1.9 is in CHECK6_FIXTURE_EXCLUDE
        acs = [{"id": "AC1.1.9", "epic": 99}]
        test_refs = {"AC1.1.9": {"tests/test_x.py"}}
        violations = ldc.check_test_id_epic_alignment(acs, test_refs)
        assert violations == []

    def test_missing_registry_entry_no_double_report(self):
        # If AC not in registry, check6 stays silent (check4 handles it)
        test_refs = {"AC99.1.1": {"tests/test_x.py"}}
        violations = ldc.check_test_id_epic_alignment([], test_refs)
        assert violations == []

    def test_non_integer_epic_field(self):
        acs = [{"id": "AC1.1.1", "epic": "not-a-number"}]
        test_refs = {"AC1.1.1": {"tests/test_x.py"}}
        violations = ldc.check_test_id_epic_alignment(acs, test_refs)
        assert len(violations) == 1
        assert "non-integer" in violations[0].message


# ---------------------------------------------------------------------------
# list_epic_files (smoke test — uses real filesystem)
# ---------------------------------------------------------------------------


class TestListEpicFiles:
    def test_returns_list(self):
        files = ldc.list_epic_files()
        # Should return a list (possibly empty if run outside repo, but no crash)
        assert isinstance(files, list)


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestMain:
    def _make_env(self, tmp_path):
        """Build a minimal passing environment in tmp_path and monkey-patch module globals."""
        vision = tmp_path / "vision.md"
        vision.write_text(
            '# Vision\n\n<a id="decision-1-accounting"></a>\nSome text.\n'
        )

        # EPIC dir
        epic_dir = tmp_path / "docs" / "project"
        epic_dir.mkdir(parents=True)
        epic_file = epic_dir / "EPIC-001.phase0-setup.md"
        epic_file.write_text(
            "> **Vision Anchor**: `decision-1-accounting`\n\nAC1.1.1 present here\n"
        )

        # registry
        reg = tmp_path / "docs" / "ac_registry.yaml"
        reg.write_text(
            "version: '1.0'\ngroups:\n"
            "  AC1:\n"
            "    AC1.1:\n"
            "      - id: AC1.1.1\n"
            "        epic: 1\n"
            "        epic_name: phase0-setup\n"
            "        description: 'Setup'\n"
            "        mandatory: true\n"
        )
        infra = tmp_path / "docs" / "infra_registry.yaml"
        infra.write_text("version: '1.0'\ngroups: {}\n")

        ci_cd = tmp_path / "docs" / "ssot" / "ci-cd.md"
        ci_cd.parent.mkdir(parents=True, exist_ok=True)
        ci_cd.write_text(
            "\n".join(ldc.PROOF_PLACEMENT_REQUIRED_TOKENS),
            encoding="utf-8",
        )

        # test file
        tests = tmp_path / "apps" / "backend" / "tests"
        tests.mkdir(parents=True)
        (tests / "test_setup.py").write_text("# AC1.1.1\n")
        (tmp_path / "apps" / "backend" / "README.md").write_text(
            "# Backend\n\n## SSOT Links\n\n- docs\n",
            encoding="utf-8",
        )
        (tmp_path / "apps" / "frontend").mkdir(parents=True)
        (tmp_path / "apps" / "frontend" / "README.md").write_text(
            "# Frontend\n\n## SSOT Links\n\n- docs\n",
            encoding="utf-8",
        )
        (tests / "README.md").write_text(
            "# Backend Tests\n\n## SSOT Links\n\n- docs\n",
            encoding="utf-8",
        )

        return vision, epic_dir, epic_file, reg, infra, tests

    def test_passing_run(self, tmp_path):
        vision, epic_dir, epic_file, reg, infra, tests = self._make_env(tmp_path)
        with (
            mock.patch.object(ldc._base, "VISION_PATH", vision),
            mock.patch.object(ldc._base, "EPIC_DIR", epic_dir),
            mock.patch.object(ldc._base, "AC_REGISTRY", reg),
            mock.patch.object(ldc._base, "INFRA_REGISTRY", infra),
            mock.patch.object(ldc._base, "TEST_ROOTS", [tests]),
            mock.patch.object(ldc, "CHECK6_TEST_ROOTS", [tests]),
            mock.patch.object(ldc._base, "REPO_ROOT", tmp_path),
            mock.patch("sys.argv", ["lint_doc_consistency.py"]),
        ):
            result = ldc.main()
        assert result == 0

    def test_verbose_flag(self, tmp_path, capsys):
        vision, epic_dir, epic_file, reg, infra, tests = self._make_env(tmp_path)
        with (
            mock.patch.object(ldc._base, "VISION_PATH", vision),
            mock.patch.object(ldc._base, "EPIC_DIR", epic_dir),
            mock.patch.object(ldc._base, "AC_REGISTRY", reg),
            mock.patch.object(ldc._base, "INFRA_REGISTRY", infra),
            mock.patch.object(ldc._base, "TEST_ROOTS", [tests]),
            mock.patch.object(ldc, "CHECK6_TEST_ROOTS", [tests]),
            mock.patch.object(ldc._base, "REPO_ROOT", tmp_path),
            mock.patch("sys.argv", ["lint_doc_consistency.py", "--verbose"]),
        ):
            result = ldc.main()
        assert result == 0
        captured = capsys.readouterr()
        assert "EPIC files scanned" in captured.out

    def test_missing_vision_md_exits_1(self, tmp_path):
        with (
            mock.patch.object(ldc._base, "VISION_PATH", tmp_path / "nonexistent.md"),
            mock.patch("sys.argv", ["lint_doc_consistency.py"]),
        ):
            result = ldc.main()
        assert result == 1

    def test_missing_epic_dir_exits_1(self, tmp_path):
        vision = tmp_path / "vision.md"
        vision.write_text(MINIMAL_VISION_MD)
        with (
            mock.patch.object(ldc._base, "VISION_PATH", vision),
            mock.patch.object(ldc._base, "EPIC_DIR", tmp_path / "nonexistent"),
            mock.patch("sys.argv", ["lint_doc_consistency.py"]),
        ):
            result = ldc.main()
        assert result == 1

    def test_no_epic_files_exits_1(self, tmp_path):
        vision = tmp_path / "vision.md"
        vision.write_text(MINIMAL_VISION_MD)
        epic_dir = tmp_path / "docs" / "project"
        epic_dir.mkdir(parents=True)
        with (
            mock.patch.object(ldc._base, "VISION_PATH", vision),
            mock.patch.object(ldc._base, "EPIC_DIR", epic_dir),
            mock.patch("sys.argv", ["lint_doc_consistency.py"]),
        ):
            result = ldc.main()
        assert result == 1

    def test_violations_print_and_exit_1(self, tmp_path):
        vision = tmp_path / "vision.md"
        vision.write_text(MINIMAL_VISION_MD)
        epic_dir = tmp_path / "docs" / "project"
        epic_dir.mkdir(parents=True)
        # EPIC with missing anchor
        (epic_dir / "EPIC-001.setup.md").write_text("# No anchor\n")
        reg = tmp_path / "docs" / "ac_registry.yaml"
        reg.parent.mkdir(parents=True, exist_ok=True)
        reg.write_text("version: '1.0'\ngroups: {}\n")
        infra = tmp_path / "docs" / "infra_registry.yaml"
        infra.write_text("version: '1.0'\ngroups: {}\n")
        tests = tmp_path / "tests"
        tests.mkdir()
        with (
            mock.patch.object(ldc._base, "VISION_PATH", vision),
            mock.patch.object(ldc._base, "EPIC_DIR", epic_dir),
            mock.patch.object(ldc._base, "AC_REGISTRY", reg),
            mock.patch.object(ldc._base, "INFRA_REGISTRY", infra),
            mock.patch.object(ldc._base, "TEST_ROOTS", [tests]),
            mock.patch.object(ldc, "CHECK6_TEST_ROOTS", [tests]),
            mock.patch.object(ldc._base, "REPO_ROOT", tmp_path),
            mock.patch("sys.argv", ["lint_doc_consistency.py"]),
        ):
            result = ldc.main()
        assert result == 1
