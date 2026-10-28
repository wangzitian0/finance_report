"""Tests for tools/lint_doc_consistency.py."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from common.testing import lint_doc_consistency as ldc

MINIMAL_VISION_MD = """\
# Vision

<a id="decision-1-accounting"></a>
Some text.
"""


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


def test_module_readmes_are_thin_passes_for_repo() -> None:
    """Module README files remain pointers to SSOT owners."""
    assert ldc.check_module_readmes_are_thin() == []


def test_AC14_1_7_generated_analysis_snapshots_are_absent(tmp_path: Path) -> None:
    """AC-meta.doc-consistency.1: AC14.1.7: Generated analysis snapshots are not checked into docs/project."""
    snapshot = tmp_path / "docs" / "project" / "test-ac-coverage-report.md"
    assert ldc.check_generated_analysis_snapshots_absent((snapshot,)) == []
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("# generated\n", encoding="utf-8")
    violations = ldc.check_generated_analysis_snapshots_absent((snapshot,))
    assert len(violations) == 1
    assert violations[0].check == "check13_generated_analysis_snapshots_absent"


def test_AC14_1_8_reconciliation_thresholds_are_code_owned(tmp_path: Path) -> None:
    """AC-meta.doc-consistency.2: AC14.1.8: Reconciliation threshold prose points to code/config owners."""
    doc = tmp_path / "reconciliation.md"
    doc.write_text(
        "### Reconciliation Thresholds\n"
        "Runtime values are owned by apps/backend/config/reconciliation.yaml and "
        "apps/backend/src/reconciliation/extension/matching.py through DEFAULT_CONFIG and "
        "load_reconciliation_config. Overrides use RECONCILIATION_AUTO_ACCEPT_THRESHOLD "
        "and RECONCILIATION_REVIEW_THRESHOLD.\n",
        encoding="utf-8",
    )
    assert ldc.check_reconciliation_thresholds_are_code_owned(doc) == []

    doc.write_text(
        "This table is the single authoritative definition of reconciliation score thresholds.",
        encoding="utf-8",
    )
    violations = ldc.check_reconciliation_thresholds_are_code_owned(doc)
    assert any("single authority" in v.message for v in violations)


def test_AC14_1_10_frontend_raw_fetch_is_limited_to_api_wrapper(tmp_path: Path) -> None:
    """AC-meta.doc-consistency.3: AC14.1.10: Frontend raw fetch is limited to the API wrapper."""
    src = tmp_path / "apps" / "frontend" / "src"
    api = src / "lib" / "api.ts"
    page = src / "app" / "page.tsx"
    test_file = src / "__tests__" / "api.test.ts"
    api.parent.mkdir(parents=True)
    page.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    api.write_text(
        "export const apiFetch = () => fetch('/api/test')\n", encoding="utf-8"
    )
    page.write_text(
        "export const load = () => fetch('/api/accounts')\n", encoding="utf-8"
    )
    test_file.write_text("expect(fetch).toBeDefined()\n", encoding="utf-8")

    violations = ldc.check_frontend_raw_fetch_usage(src, {api})
    assert len(violations) == 1
    assert "app/page.tsx:1" in violations[0].message


def test_AC8_13_77_active_stub_orphan_fails() -> None:
    """AC-testing.acgates.10: AC8.13.77: Active stub registry entries cannot bypass EPIC ownership."""
    acs = [{"id": "AC1.1.1", "status": "stub", "mandatory": False}]
    violations = ldc.check_registry_to_epic(acs, {})
    assert len(violations) == 1
    assert "AC1.1.1" in violations[0].message
    assert (
        ldc.check_registry_to_epic(
            [{"id": "AC1.1.1", "description": "~~historical placeholder~~"}], {}
        )
        == []
    )


def test_AC8_13_81_doc_can_reference_code_owned_threshold_without_number(
    tmp_path: Path,
) -> None:
    """AC-testing.governance.2: AC8.13.81: Coverage threshold docs should link to the code owner."""
    doc = tmp_path / "tdd.md"
    doc.write_text(
        "Backend local coverage threshold is code-owned by "
        "`apps/backend/pyproject.toml` `--cov-fail-under`.\n",
        encoding="utf-8",
    )
    assert ldc.check_code_owned_coverage_threshold_doc(doc) == []

    doc.write_text(
        "Backend pytest keeps a 90% local source-coverage threshold.\n",
        encoding="utf-8",
    )
    violations = ldc.check_code_owned_coverage_threshold_doc(doc)
    assert len(violations) == 1
    assert "code-owned" in violations[0].message


class TestMain:
    def test_passing_and_failing_runs(self, tmp_path: Path) -> None:
        vision = tmp_path / "vision.md"
        vision.write_text(MINIMAL_VISION_MD, encoding="utf-8")
        epic_dir = tmp_path / "docs" / "project"
        epic_dir.mkdir(parents=True)
        epic_file = epic_dir / "EPIC-001.phase0-setup.md"
        epic_file.write_text(
            "> **Vision Anchor**: `decision-1-accounting`\n\nAC1.1.1 present here\n",
            encoding="utf-8",
        )
        reg = tmp_path / "docs" / "ac_registry.yaml"
        reg.write_text(
            "version: '1.0'\ngroups:\n  AC1:\n    AC1.1:\n"
            "      - id: AC1.1.1\n        epic: 1\n        epic_name: phase0-setup\n"
            "        description: 'Setup'\n        mandatory: true\n",
            encoding="utf-8",
        )
        infra = tmp_path / "docs" / "infra_registry.yaml"
        infra.write_text("version: '1.0'\ngroups: {}\n", encoding="utf-8")
        ci_cd = tmp_path / "common" / "testing" / "ci-cd.md"
        ci_cd.parent.mkdir(parents=True, exist_ok=True)
        ci_cd.write_text(
            "\n".join(ldc.PROOF_PLACEMENT_REQUIRED_TOKENS), encoding="utf-8"
        )
        tests = tmp_path / "apps" / "backend" / "tests"
        tests.mkdir(parents=True)
        (tests / "test_setup.py").write_text("# AC1.1.1\n", encoding="utf-8")
        for rel in (
            "apps/backend/README.md",
            "apps/frontend/README.md",
            "apps/backend/tests/README.md",
        ):
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# Module\n\n## SSOT Links\n\n- docs\n", encoding="utf-8")

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
            assert ldc.main() == 0
            epic_file.write_text("# No anchor\n", encoding="utf-8")
            assert ldc.main() == 1
